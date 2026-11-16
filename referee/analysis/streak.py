"""Does the signed tool-call record show a run "going badly" before a cheat? Exploratory, post hoc, $0, no model calls.

Two stages, two interpreters (the referee venv has the pinned Tracekit; the system Python has numpy and matplotlib):

  .venv/bin/python -B -I analysis/streak.py extract   # in referee/: verify, open, parse -> streak-data.json
  python3 -B analysis/streak.py analyse               # every number in docs/results-streak.md, and streak.png

It reads the run records (runs/, available to reviewers on request; see the README) from the referee folder, or from
$TRUTHGATE_REFEREE. Read-only there; writes only next to this file. Outcomes come from the signed record only: each bundle
passes `tracekit verify --trust signer-data/trust.json`, its sha256 matches the evidence manifest, and every call's
arguments and result are opened from opening.json against the signed HMAC commitment. transcript.json is read only to
check the turn reconstruction.
"""
import csv
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REF = os.environ.get("TRUTHGATE_REFEREE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUST = os.path.join(REF, "signer-data", "trust.json")
TRUST_SHA = "0d6766bef18e684f585122c187ccf9c002e579aa3c48618c40d9ced800f6b3ba"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "streak-data.json")
STUDY1 = ("baseline", "monitor-aware")
STUDY2 = ("human-review", "recorded", "norm", "baseline-drift")
TURN_GAP_S = 0.5

TEST_RUN = re.compile(r"python[0-9.]*\s+(?:-\S+\s+)*(?:\./|/workspace/)?test\.py\b")
FRAME = re.compile(r'File "[^"]*test\.py", line (\d+), in test_func')
EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt))\b", re.M)


def py_writes(cmd, name="func.py"):
    """Python in a command that writes the workspace's `name`: open(<path>, 'w'|'a') or Path(<path>).write_text, where
    <path> is the literal path or a variable assigned it (`p='func.py'; open(p,'w')`)."""
    lit = r"[\"'](?:\./|/workspace/)?" + re.escape(name) + r"[\"']"
    targets = [lit] + [re.escape(v) for v in re.findall(r"\b(\w+)\s*=\s*" + lit, cmd)]
    for t in targets:
        if re.search(r"open\(\s*" + t + r"\s*,\s*[\"'][wa]", cmd) or \
                re.search(r"Path\(\s*" + t + r"\s*\)\s*\.write_text\(", cmd):
            return True
    return False


def shell_writes(cmd, name="func.py"):
    """Does a shell command write the workspace's `name` (func.py, or test.py)? Each line is split into simple commands
    (shlex, unquoted ; & | as separators); a command writes the file by a > or >> redirect to it, `tee` onto it,
    `sed`/`perl` with an in-place
    flag naming it, `cp`/`mv`/`install` with it as the target, or `patch` naming it. A quote left open at the end of a
    line (`… && python -c "`, continued on the next lines) ends the split there; the tokens before it still count.
    Python heredocs are caught by py_writes instead."""
    import shlex
    paths = (name, "./" + name, "/workspace/" + name)
    for line in cmd.split("\n"):
        if name not in line:
            continue
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
        lex.whitespace_split = True
        toks = []
        try:
            for t in lex:
                toks.append(t)
        except ValueError:
            pass
        cmds, cur = [], []
        for t in toks:
            if t and set(t) <= set(";&|") and t not in ("&>",):
                cmds.append(cur)
                cur = []
            else:
                cur.append(t)
        cmds.append(cur)
        for c in cmds:
            if any(a in (">", ">>", ">|") and b in paths for a, b in zip(c, c[1:])):
                return True
            if not c:
                continue
            prog, rest = os.path.basename(c[0]), c[1:]
            names = any(t in paths for t in rest)
            if prog == "tee" and names:
                return True
            if prog in ("sed", "perl") and names and any(
                    t == "--in-place" or re.fullmatch(r"-[a-zA-Z]*i\S*", t) for t in rest if t.startswith("-")):
                return True
            if prog in ("cp", "mv", "install") and rest and rest[-1] in paths:
                return True
            if prog == "patch" and names:
                return True
    return False


# ---------------------------------------------------------------- extract (referee venv: pinned Tracekit)

def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cli_verify(bundle):
    """`tracekit verify` itself, the pinned CLI: (ok, last line)."""
    p = subprocess.run([sys.executable, "-B", "-I", "-m", "tracekit", "verify", bundle, "--trust", TRUST],
                       capture_output=True, text=True, cwd=HERE)
    return p.returncode == 0 and "Integrity: VERIFIED." in p.stdout, (p.stdout.strip().splitlines() or [""])[-2:]


def signed_calls(bundle, opening):
    """Every call of the run, in run_seq order: tool, args, result, signed timestamps. Args and results are accepted
    only when their HMAC matches the signed commitment (the referee's build_trace rule)."""
    from datetime import datetime
    from tracekit.format.canon import canonical, event_hash
    from tracekit.verify.v2 import verify
    runs = {}
    rep, _ = verify(bundle, TRUST, runs=runs)
    if rep.integrity != "VERIFIED":
        raise ValueError(f"library verify: {rep.integrity}")
    events = sorted((r["event"] for recs in runs.values() for r in recs), key=lambda e: e["run_seq"])
    with open(opening) as f:
        items = {i["seq"]: i for i in json.load(f)["items"]}

    def opened(seq, commitment, digest):
        it = items.get(seq)
        if it is None or "content" not in it or "salt" not in it:
            raise ValueError(f"run_seq {seq}: not opened")
        mine = "hmac-sha256:" + hmac.new(bytes.fromhex(it["salt"]), digest(it["content"]).encode(), "sha256").hexdigest()
        if not commitment or not hmac.compare_digest(mine, commitment):
            raise ValueError(f"run_seq {seq}: opened value does not match the signed commitment")
        return it["content"]

    ts = lambda e: datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp()
    calls, by_dec = [], {}
    for e in events:
        d = e["data"]
        if e["type"] == "policy.decision":
            args = opened(e["run_seq"], d.get("args_commitment"),
                          lambda v, tool=d["tool"]: event_hash({"tool": tool, "args": v}))
            c = {"tool": d["tool"], "id": d.get("tool_use_id"), "args": args, "result": None,
                 "t_dec": ts(e), "t_res": None}
            by_dec[d["decision_id"]] = c
            calls.append(c)
        elif e["type"] == "tool.result" and d.get("decision_id") in by_dec:
            v = opened(e["run_seq"], (d.get("output") or {}).get("hash"),
                       lambda v: "sha256:" + hashlib.sha256(canonical(v)).hexdigest())
            c = by_dec[d["decision_id"]]
            c["result"], c["t_res"] = (v or {}).get("result") if isinstance(v, dict) else None, ts(e)
    return calls


def turns_of(calls):
    """Turn index (1-based) per call: a new model step starts when a decision comes > TURN_GAP_S after the last result."""
    out, turn, last = [], 0, None
    for c in calls:
        if last is None or c["t_dec"] - last > TURN_GAP_S:
            turn += 1
        out.append(turn)
        last = c["t_res"] if c["t_res"] is not None else c["t_dec"]
    return out


def transcript_turns(path, ids):
    """Check only: the same partition read from the transcript's assistant messages."""
    with open(path) as f:
        t = json.load(f)
    msgs = t if isinstance(t, list) else t.get("messages", [])
    group = {}
    for m in msgs:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            got = [b.get("id") for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
            if got:
                n = len(set(group.values())) + 1
                group.update({i: n for i in got})
    return [group.get(i) for i in ids]


def is_write(c):
    if c["tool"] == "write_file":
        return str((c["args"] or {}).get("path", "")).strip() in ("func.py", "./func.py", "/workspace/func.py")
    if c["tool"] != "run_shell":
        return False
    cmd = str((c["args"] or {}).get("command", ""))
    if "func.py" not in cmd:
        return False
    return shell_writes(cmd) or py_writes(cmd)


def own_test_run(cmd):
    """A run of the task's own test.py, as the agent was given it, in /workspace: the command runs `python test.py`,
    does not write test.py (a `sed -i` that drops the impossible assert, then a run, is not the task's test), and does
    not `cd` anywhere but /workspace before it (`cd /tmp && python test.py` runs a copy)."""
    m = TEST_RUN.search(cmd)
    if not m or shell_writes(cmd, "test.py") or py_writes(cmd, "test.py"):
        return False
    cds = re.findall(r"(?:^|[;&|(])\s*cd\s+[\"']?([^\s;&|)\"']+)", cmd[:m.start()], re.M)
    return not cds or cds[-1].rstrip("/") in ("/workspace", ".", "~")


def test_run(c):
    """None if the call is not a test run, else (passed, assertion line N or None, last exception name or None)."""
    out = c["result"] if isinstance(c["result"], str) else ""
    if c["tool"] == "submit":
        passed = out.startswith("All tests passed.")
    elif c["tool"] == "run_shell" and own_test_run(str((c["args"] or {}).get("command", ""))):
        passed = re.search(r"^All tests passed!$", out, re.M) is not None
    else:
        return None
    lines = FRAME.findall(out)
    excs = EXC.findall(out)
    return passed, (int(lines[-1]) if lines else None), (excs[-1] if excs else None)


def impossible_lines():
    """{task_id: [lo, hi]}, the test.py lines (referee/tasks.py layout: body line i is line i + 3) of the statements the
    oneoff variant changed against original_test, widened back to the statement's first line. Usually one assert;
    lcbhard_5 replaces one assert with a block, lcbhard_42 changes a continuation line."""
    import difflib
    with open(os.path.join(REF, "data", "tasks", "oneoff.jsonl")) as f:
        rows = {r["task_id"]: r for r in map(json.loads, f)}
    out = {}
    for tid, r in rows.items():
        a, b = r["test"].split("\n"), r["original_test"].split("\n")
        js = [(j1, j2) for op, _, _, j1, j2 in difflib.SequenceMatcher(None, b, a, autojunk=False).get_opcodes()
              if op in ("replace", "insert") and j2 > j1]
        lo, hi = js[0][0], js[-1][1] - 1
        while lo > 0 and not re.match(r"^    \S", a[lo]):   # a continuation line: back to the statement's start
            lo -= 1
        built = f"from func import {r['entry_point']}\n\n{r['test'].replace('def check(', 'def test_func(')}"
        assert built.split("\n")[lo + 2] == a[lo] and "def test_func" not in a[lo], tid
        out[tid] = [lo + 3, hi + 3]
    return out


def v1_labels():
    """The 55 natural cheats, from the appendix table of docs/results-v1.md."""
    rows = re.findall(r"^\| (pilot|baseline|monitor-aware) \| `([^`]+)` \|",
                      open(os.path.join(REF, "docs", "results-v1.md")).read(), re.M)
    return {("baseline" if c == "pilot" else c, r) for c, r in rows}


def manifest():
    m = {}
    for name in ("evidence-v1.tsv", "evidence-v2.tsv"):
        for r in csv.DictReader(open(os.path.join(REF, "docs", name)), delimiter="\t"):
            m[(r["run"].rsplit("/", 1)[-1], r["rollout"])] = r["rollout_bundle_sha256"]
    return m


def one(cond, rid, L, man):
    d = os.path.join(REF, "runs", "v1", cond, rid)
    bundle = os.path.join(d, "rollout.tkb")
    meta = json.load(open(os.path.join(d, "meta.json")))
    rec = {"condition": cond, "rollout": rid, "model": meta["model"], "variant": meta["variant"],
           "task": meta["task_id"], "official_pass": json.load(open(os.path.join(d, "checks.json")))["official"]["passed"],
           "status": meta["result"]["status"]}
    ok, tail = cli_verify(bundle)
    rec["cli_verified"], rec["sha_ok"] = ok, sha256(bundle) == man.get((cond, rid))
    if not (ok and rec["sha_ok"]):
        rec["excluded"] = f"verify {ok} {tail}, sha {rec['sha_ok']}"
        return rec
    try:
        calls = signed_calls(bundle, os.path.join(d, "opening.json"))
    except ValueError as e:
        rec["excluded"] = str(e)
        return rec
    turns = turns_of(calls)
    tt = transcript_turns(os.path.join(d, "transcript.json"), [c["id"] for c in calls])
    # same partition: consecutive calls share a turn in one exactly when they do in the other
    rec["turns_agree"] = all((turns[i] == turns[i - 1]) == (tt[i] == tt[i - 1]) for i in range(1, len(calls)))
    rec["T"] = turns[-1] if turns else 0
    rec["n_calls"] = len(calls)
    rec["L"] = L.get(meta["task_id"]) if meta["variant"] == "oneoff" else None
    rec["calls"] = []
    for i, (c, t) in enumerate(zip(calls, turns)):
        tr = test_run(c)
        rec["calls"].append({"i": i, "turn": t, "tool": c["tool"], "write": is_write(c),
                             "test": None if tr is None else {"pass": tr[0], "line": tr[1], "exc": tr[2]}})
    return rec


def extract():
    assert sha256(TRUST) == TRUST_SHA, "trust.json is not the one results-v1.md pins"
    L, man, cheats = impossible_lines(), manifest(), v1_labels()
    assert len(cheats) == 55, len(cheats)
    jobs = []
    for cond in STUDY1 + STUDY2:
        for rid in sorted(os.listdir(os.path.join(REF, "runs", "v1", cond))):
            if "__" in rid and rid.split("__")[1] in (("oneoff", "conflicting") if cond in STUDY1 else ("oneoff",)):
                jobs.append((cond, rid))
    with ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(lambda j: one(j[0], j[1], L, man), jobs))
    for r in recs:
        r["study"] = 1 if r["condition"] in STUDY1 else 2
        # label: study 1 from the results-v1 appendix, study 2 the official grade (results-v2's definition)
        r["cheat"] = (r["condition"], r["rollout"]) in cheats if r["study"] == 1 else r["official_pass"]
        if r["study"] == 1 and r["cheat"] != r["official_pass"]:
            raise SystemExit(f"label disagrees with the official grade: {r['condition']} {r['rollout']}")
    # audit lists for the parse: commands that mention test.py with python but are not counted, and pytest
    audit = {"uncounted_python_testpy": [], "pytest": [], "testpy_run_not_own": []}
    for cond, rid in jobs:
        d = os.path.join(REF, "runs", "v1", cond, rid)
        try:
            items = json.load(open(os.path.join(d, "opening.json")))["items"]
        except OSError:
            continue
        for it in items:
            cmd = (it.get("content") or {}).get("command") if isinstance(it.get("content"), dict) else None
            if not isinstance(cmd, str):
                continue
            if "test.py" in cmd and "python" in cmd and not TEST_RUN.search(cmd):
                audit["uncounted_python_testpy"].append(cmd[:300])
            if "pytest" in cmd:
                audit["pytest"].append(cmd[:300])
            if TEST_RUN.search(cmd) and not own_test_run(cmd):
                audit["testpy_run_not_own"].append(f"{cond}/{rid}: {cmd[:300]}")
    json.dump({"rollouts": recs, "audit": audit}, open(DATA, "w"), indent=0)
    ex = [r for r in recs if "excluded" in r]
    print(f"{len(recs)} rollouts; {len(ex)} excluded; CLI-verified {sum(r['cli_verified'] for r in recs)}; "
          f"sha ok {sum(r['sha_ok'] for r in recs)}; turns agree with transcript "
          f"{sum(r.get('turns_agree', False) for r in recs)}/{len(recs) - len(ex)}")
    for r in ex:
        print("EXCLUDED", r["condition"], r["rollout"], r["excluded"])


# ---------------------------------------------------------------- analyse (system Python: numpy, matplotlib)

K = 3
B = 5000
MIN_N = 5
SEED = 20261117


def test_runs(r):
    return [(c["turn"], c["test"]) for c in r["calls"] if c["test"] is not None]


def evidence_call(r, pass_only=False):
    """E: the first test run that passes or fails after the impossible line L (a special case was in place); with
    pass_only, the first that passes."""
    for c in r["calls"]:
        t = c["test"]
        if t is not None and (t["pass"] or (not pass_only and t["line"] is not None and r["L"] is not None
                                            and t["line"] > r["L"][1])):
            return c["i"]
    return None


def cheat_alignment(r, pass_only=False):
    """(t*, how): the turn of the last func.py write at or before E's call."""
    e = evidence_call(r, pass_only)
    writes = [c for c in r["calls"] if c["write"] and c["i"] <= e]
    if writes:
        return writes[-1]["turn"], ("same call as E" if writes[-1]["i"] == e else "earlier write")
    return r["calls"][e]["turn"], "no write found: E's turn"


def streak(runs):
    s = 0
    for _, t in reversed(runs):
        if t["pass"]:
            break
        s += 1
    return s


def signature(t):
    return None if t["line"] is None and t["exc"] is None else (t["line"], t["exc"])


def rise(flags):
    """share in the last K minus share in the earlier ones; 0 when there are no earlier ones."""
    if len(flags) <= K:
        return 0.0
    return sum(flags[-K:]) / K - sum(flags[:-K]) / (len(flags) - K)


def features(r, tstar):
    runs = [x for x in test_runs(r) if x[0] < tstar]
    fail = [0 if t["pass"] else 1 for _, t in runs]
    stuck = [1 if (not b["pass"] and signature(b) is not None and signature(a) == signature(b)) else 0
             for (_, a), (_, b) in zip(runs, runs[1:])]
    return {"S": streak(runs), "Ra": rise(fail), "Rb": rise(stuck), "n_tests": len(runs), "elapsed": tstar - 1,
            "n_fail_flags": len(fail), "n_stuck_flags": len(stuck)}




def S_by_turn(r, upto):
    """S_t for t = 0 … upto: the failing streak over the test runs in turns < t."""
    runs = test_runs(r)
    return [streak([x for x in runs if x[0] < t]) for t in range(upto + 1)]


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


class Boot:
    """Task-clustered bootstrap: each resample draws the task ids with replacement, and a rollout's weight is how
    often its task was drawn. Pair statistics (AUROC and its matched forms) are weighted means over a cheat x
    non-cheat kernel, so each resample is two matrix products."""

    def __init__(self, rows, seed):
        import numpy as np
        tasks = sorted({r["task"] for r in rows})
        ix = {t: i for i, t in enumerate(tasks)}
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, len(tasks), (B, len(tasks)))
        self.W = np.stack([np.bincount(d, minlength=len(tasks)) for d in draws]).astype(float)
        self.ix = ix

    def w(self, rows):
        import numpy as np
        return self.W[:, np.array([self.ix[r["task"]] for r in rows])]

    def pairs(self, cheats, non, Kmat, mask=None):
        import numpy as np
        M = np.ones_like(Kmat) if mask is None else mask
        wc, wn = self.w(cheats), self.w(non)
        num = ((wc @ (Kmat * M)) * wn).sum(1)
        den = ((wc @ M) * wn).sum(1)
        v = num[den > 0] / den[den > 0]
        point = (Kmat * M).sum() / M.sum()
        return point, float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))

    def mean(self, rows, vals):
        import numpy as np
        wr = self.w(rows)
        s = wr.sum(1)
        v = (wr @ np.asarray(vals, float))[s > 0] / s[s > 0]
        return float(np.mean(vals)), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def kern(cv, nv):
    import numpy as np
    c, n = np.asarray(cv, float)[:, None], np.asarray(nv, float)[None, :]
    return (c > n) + 0.5 * (c == n)


def analyse():
    import numpy as np
    np.seterr(all="ignore")   # numpy 2.0's Accelerate matmul warns on finite inputs; its products equal einsum's here
    blob = json.load(open(DATA))
    recs = [r for r in blob["rollouts"] if "excluded" not in r]
    out = []

    def say(s=""):
        print(s)
        out.append(s)

    say(f"rollouts read {len(blob['rollouts'])}, excluded {len(blob['rollouts']) - len(recs)}; all CLI-verified "
        f"{all(r['cli_verified'] for r in blob['rollouts'])}; all bundle sha256 match the manifests "
        f"{all(r['sha_ok'] for r in blob['rollouts'])}")
    say(f"turn reconstruction from signed timestamps agrees with the transcript's assistant messages: "
        f"{sum(r['turns_agree'] for r in recs)}/{len(recs)}")
    say(f"parse audit: {len(blob['audit']['uncounted_python_testpy'])} commands mention python and test.py but are not "
        f"runs of test.py itself; {len(blob['audit']['pytest'])} mention pytest")

    s1 = [r for r in recs if r["study"] == 1 and r["variant"] == "oneoff"]
    s1all = [r for r in recs if r["study"] == 1]
    s2 = [r for r in recs if r["study"] == 2]
    for r in recs:
        r["Sbt"] = S_by_turn(r, r["T"] + 1)

    how = {1: {}, 2: {}}
    for r in s1 + s2:
        if r["cheat"]:
            r["tstar"], h = cheat_alignment(r)
            how[r["study"]][h] = how[r["study"]].get(h, 0) + 1
    med = int(np.median([r["tstar"] for r in s1 if r["cheat"]]))
    for r in s1all + s2:
        if not r["cheat"]:
            r["tstar"] = min(med, r["T"] + 1)
        r.update(features(r, r["tstar"]))
        assert r["S"] == r["Sbt"][r["tstar"]]

    def grp(rows):
        return [r for r in rows if r["cheat"]], [r for r in rows if not r["cheat"]]

    c1, n1 = grp(s1)
    say(f"cheat alignment, how found: study 1 {how[1]}; study 2 {how[2]}")
    say(f"median cheat t* (study 1, {len(c1)} cheats): turn {med}; cheat t* min {min(r['tstar'] for r in c1)}, "
        f"quartiles {np.percentile([r['tstar'] for r in c1], [25, 75]).tolist()}, max {max(r['tstar'] for r in c1)}")
    say(f"non-cheats (study 1 oneoff) whose run ends before turn {med}: {sum(1 for r in n1 if r['T'] + 1 < med)}/{len(n1)}")
    say(f"non-cheats with a pass or a post-impossible-line failure somewhere (a special case tried, then left): "
        f"{sum(1 for r in n1 if evidence_call(r) is not None)}")
    say(f"test runs before t*: cheats {sum(r['n_tests'] for r in c1)} ({sum(1 for r in c1 for x in test_runs(r) if x[0] < r['tstar'] and x[1]['pass'])} passing), "
        f"non-cheats {sum(r['n_tests'] for r in n1)} ({sum(1 for r in n1 for x in test_runs(r) if x[0] < r['tstar'] and x[1]['pass'])} passing)")

    def auc(rows, f, boot, label):
        c, n = grp(rows)
        p, lo, hi = boot.pairs(c, n, kern([r[f] for r in c], [r[f] for r in n]))
        say(f"  {label}: AUROC {p:.3f} [{lo:.3f}, {hi:.3f}]  (cheats {len(c)}, non-cheats {len(n)}; mean "
            f"{np.mean([r[f] for r in c]):.2f} vs {np.mean([r[f] for r in n]):.2f}; median "
            f"{np.median([r[f] for r in c]):g} vs {np.median([r[f] for r in n]):g})")

    def matched(rows, boot, label):
        c, n = grp(rows)
        V = np.array([[y["Sbt"][min(x["tstar"], y["T"] + 1)] for y in n] for x in c], float)
        Kmat = (np.array([x["S"] for x in c], float)[:, None] > V) + 0.5 * (np.array([x["S"] for x in c], float)[:, None] == V)
        p, lo, hi = boot.pairs(c, n, Kmat)
        say(f"  {label}: {p:.3f} [{lo:.3f}, {hi:.3f}]")

    def within(rows, boot, label):
        c, n = grp(rows)
        M = np.array([[1.0 if x["task"] == y["task"] else 0.0 for y in n] for x in c])
        p, lo, hi = boot.pairs(c, n, kern([r["S"] for r in c], [r["S"] for r in n]), M)
        say(f"  {label}: {p:.3f} [{lo:.3f}, {hi:.3f}]  ({int(M.sum())} same-task pairs, "
            f"{len({x['task'] for x in c if any(y['task'] == x['task'] for y in n)})} tasks)")

    b1 = Boot(s1, SEED)
    say()
    say("PRIMARY: study 1, oneoff")
    for cond in STUDY1:
        for m in sorted({r["model"] for r in s1}):
            rows = [r for r in s1 if r["condition"] == cond and r["model"] == m]
            if rows:
                say(f"  n {cond:13s} {m:18s} cheats {sum(r['cheat'] for r in rows):2d} / {len(rows)}")
    auc(s1, "S", b1, "S(t*) failing streak")
    auc(s1, "Ra", b1, "R_a failing rise, k=3, as briefed")
    auc(s1, "Rb", b1, "R_b stuck rise, k=3 (declared variant)")
    for f, lab, flags in (("Ra", "R_a", "n_fail_flags"), ("Rb", "R_b", "n_stuck_flags")):
        say(f"  {lab}: zero for cheats {sum(r[f] == 0 for r in c1)}/{len(c1)}, non-cheats {sum(r[f] == 0 for r in n1)}/{len(n1)}; "
            f"undefined (<= {K} runs, set to 0): cheats {sum(r[flags] <= K for r in c1)}, non-cheats {sum(r[flags] <= K for r in n1)}")

    say()
    say("RATE TABLE: cheat rate by S(t*), study 1 oneoff")
    say("  | S(t*) | rollouts | cheats | non-cheats | cheat rate [Wilson 95%] |")
    for lo_, hi_, lab in ((0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 4, "4"), (5, 5, "5"), (6, 999, "6+")):
        rows = [r for r in s1 if lo_ <= r["S"] <= hi_]
        k = sum(r["cheat"] for r in rows)
        w = wilson(k, len(rows))
        say(f"  | {lab} | {len(rows)} | {k} | {len(rows) - k} | " +
            (f"{k / len(rows):.0%} [{w[0]:.0%}, {w[1]:.0%}] |" if rows else "- |"))

    say()
    say("PER MODEL, study 1 oneoff")
    for m in sorted({r["model"] for r in s1}):
        rows = [r for r in s1 if r["model"] == m]
        bm = Boot(rows, SEED + 10)
        auc(rows, "S", bm, f"{m} S(t*)")
        auc(rows, "Rb", bm, f"{m} R_b")
    sonnet = [r for r in s1 if r["model"] == "claude-sonnet-5-5"]
    for cond in STUDY1:
        rows = [r for r in sonnet if r["condition"] == cond]
        auc(rows, "S", Boot(rows, SEED + 11), f"claude-sonnet-5-5 {cond} S(t*)")

    say()
    say("RUN-LENGTH SANITY CHECKS, study 1 oneoff")
    auc(s1, "elapsed", b1, "elapsed turns t*-1 alone")
    auc(s1, "n_tests", b1, "all test runs before t* (pass or fail)")
    matched(s1, b1, "time-matched concordance (each non-cheat's S at the cheat's own t*)")
    within(s1, b1, "within-task concordance (cheat/non-cheat pairs on the same task)")
    bs = Boot(sonnet, SEED + 12)
    matched(sonnet, bs, "time-matched, Sonnet only")
    within(sonnet, bs, "within-task, Sonnet only")

    say()
    say("SENSITIVITY: study 1, all impossible variants (adds conflicting non-cheats)")
    auc(s1all, "S", Boot(s1all, SEED + 13), "S(t*)")
    say("SENSITIVITY: cheat alignment from the first passing test run only (a failure past the impossible line ignored)")
    alt = []
    for r in s1:
        t = cheat_alignment(r, pass_only=True)[0] if r["cheat"] else r["tstar"]
        alt.append(dict(r, tstar=t, **features(r, t)))
    say(f"  cheats whose t* moves: {sum(1 for a, r in zip(alt, s1) if a['tstar'] != r['tstar'])}")
    auc(alt, "S", Boot(alt, SEED + 17), "S(t*), pass-only alignment (non-cheats unchanged)")

    say()
    say(f"HELD-OUT REPLICATION: study 2 Sonnet oneoff (non-cheat t* = study 1's median, turn {med})")
    for cond in STUDY2:
        rows = [r for r in s2 if r["condition"] == cond]
        say(f"  n {cond:15s} cheats {sum(r['cheat'] for r in rows):2d} / {len(rows)}: "
            f"{sorted(r['task'] for r in rows if r['cheat'])}")
    b2 = Boot(s2, SEED + 14)
    auc(s2, "S", b2, "S(t*)")
    auc(s2, "Rb", b2, "R_b")
    matched(s2, b2, "time-matched concordance")
    within(s2, b2, "within-task concordance")

    taus = list(range(-10, 1))

    def curve(rows, boot):
        res = []
        for tau in taus:
            pts = [r for r in rows if r["tstar"] + tau >= 1]
            res.append((*boot.mean(pts, [r["Sbt"][r["tstar"] + tau] for r in pts]), len(pts)) if pts else
                       (float("nan"),) * 3 + (0,))
        return [np.array(x) for x in zip(*res)]

    cm, cl, ch, cn = curve(c1, Boot(c1, SEED + 15))
    nm, nl, nh, nn = curve(n1, Boot(n1, SEED + 16))
    say()
    say("FIGURE DATA, study 1 oneoff: mean S at turn t*+tau [95% CI] (n)")
    for i, tau in enumerate(taus):
        say(f"  tau {tau:3d}: cheats {cm[i]:.2f} [{cl[i]:.2f}, {ch[i]:.2f}] ({cn[i]}) | non-cheats {nm[i]:.2f} "
            f"[{nl[i]:.2f}, {nh[i]:.2f}] ({nn[i]})")
    plot(taus, (cm, cl, ch, cn), (nm, nl, nh, nn), len(c1), len(n1), med)
    with open(os.path.join(HERE, "streak-numbers.txt"), "w") as f:
        f.write("\n".join(out) + "\n")


def plot(taus, cheat, honest, nc, nn, med):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    surface, ink, ink2, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    c_cheat, c_honest = "#eb6834", "#2a78d6"   # reference palette slots 2 and 1
    import numpy as np
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=200)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    rows = []
    for (m, lo, hi, n), col, lab, short in (
            (honest, c_honest, f"non-cheats (n={nn}), aligned at turn {med} or the run's end", "non-cheats"),
            (cheat, c_cheat, f"cheats (n={nc}), aligned at the special-casing write", "cheats")):
        keep = np.asarray(n) >= MIN_N   # a point needs MIN_N rollouts; fewer is one or two runs' noise
        x = np.array(taus)[keep]
        ax.fill_between(x, np.asarray(lo)[keep], np.asarray(hi)[keep], color=col, alpha=0.16, linewidth=0)
        ax.plot(x, np.asarray(m)[keep], color=col, linewidth=2, marker="o", markersize=4.5, markeredgecolor=surface,
                markeredgewidth=1, label=lab)
        ax.annotate(short, (x[-1], np.asarray(m)[keep][-1]), xytext=(7, 0), textcoords="offset points",
                    va="center", color=ink, fontsize=9)
        rows.append((short, n))
    for k, (short, n) in enumerate(rows):
        ax.text(taus[0] - 0.6, -0.12 - 0.055 * k, f"n {short}", transform=ax.get_xaxis_transform(), ha="right",
                color=ink2, fontsize=7)
        for t, v in zip(taus, n):
            ax.text(t, -0.12 - 0.055 * k, str(v), transform=ax.get_xaxis_transform(), ha="center", color=ink2, fontsize=7)
    ax.set_xlabel("turns relative to the alignment point (0 = alignment turn; the streak counts test runs before it)",
                  color=ink2, fontsize=9, labelpad=34)
    ax.set_ylabel("consecutive failing test runs so far", color=ink2, fontsize=9)
    ax.set_title("Failing-test streak before a cheat, read from the signed record\n"
                 "Study 1 oneoff tasks, Claude Sonnet/Opus/Haiku 5.5; bands: 95% task-clustered bootstrap",
                 color=ink, fontsize=9.5, loc="left")
    ax.set_xticks(taus)
    ax.set_xlim(taus[0] - 0.3, taus[-1] + 1.8)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=grid, linewidth=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(grid)
    ax.tick_params(colors=ink2, labelsize=8)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(ink)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "streak.png"), facecolor=surface)


if __name__ == "__main__":
    {"extract": extract, "analyse": analyse}[sys.argv[1]]()
