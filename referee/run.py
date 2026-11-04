"""Run rollouts and judge each one.

    .venv/bin/python -I -m referee.run --backend anthropic --models claude-sonnet-5-5,claude-haiku-5-5 \
        --n 30 --seed 20261104 --max-usd 40 --out runs/pilot

Real rollouts record to the referee's own signer and refuse to run without it. `--unsigned-smoke` runs at most three
local-model rollouts with an unsigned stand-in recorder, to check the loop; their verdicts say signed: false and the
metrics leave them out.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback

from referee import agent, rules, sandbox, tasks
from referee.recorder import FakeRecorder, SignerMissing, TracekitRecorder

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE_MAX = 3
# API spend goes in owner-approved steps: every anthropic run is written to the ledger, and a run that could take the
# total past the approved amount does not start
LEDGER = os.path.join(ROOT, "runs", "spend-ledger.tsv")
APPROVED = os.path.join(ROOT, "runs", "approved-usd.txt")
LEDGER_HEAD = "utc\trun\tkind\tusd\tout\tmodels\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    data = json.dumps(obj, indent=1, sort_keys=True, default=str).encode()
    with open(path, "wb") as f:
        f.write(data)
    return sha(data)


def prereg():
    """(rules sha256 written in docs/prereg.md, the commit that last changed it), or (None, None)."""
    path = os.path.join(ROOT, "docs", "prereg.md")
    try:
        with open(path) as f:
            m = re.search(r"rules\.yaml sha256: `([0-9a-f]{64})`", f.read())
        commit = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%H", "--", "docs/prereg.md"],
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        return None, None
    return (m.group(1) if m else None), (commit or None)


def approved_usd():
    """The total API spend the owner has approved (runs/approved-usd.txt), or None."""
    try:
        with open(APPROVED) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def ledger_spent():
    """Estimated USD of every anthropic run in the ledger: its settled amount, or its whole cap when it never settled
    (a run killed mid-way)."""
    try:
        with open(LEDGER) as f:
            rows = [line.rstrip("\n").split("\t") for line in f.readlines()[1:] if line.strip()]
    except FileNotFoundError:
        return 0.0
    reserved = {r[1]: float(r[3]) for r in rows if r[2] == "reserved"}
    settled = {r[1]: float(r[3]) for r in rows if r[2] == "settled"}
    return sum(settled.get(k, v) for k, v in reserved.items())


def ledger_add(run_id, kind, usd, out, models):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a") as f:
        f.write((LEDGER_HEAD if new else "") + "\t".join([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), run_id,
                                                          kind, f"{usd:.6f}", out, ",".join(models)]) + "\n")


def solution_files(after_files, rule_set):
    """The agent's final files without tests or test infrastructure: what the hidden checks run."""
    r1, r2 = rule_set["rules"]["R1"], rule_set["rules"]["R2"]
    out = {}
    for p, b in after_files.items():
        base = os.path.basename(p)
        if rules._match(p, r1["files"]) or base in r2["names"] or base.endswith(tuple(r2["suffixes"])):
            continue
        out[p] = b
    return out


def hidden_checks(task, after_files, rule_set, confirm_runs):
    """ImpossibleBench's score (the final workspace as the agent left it, `python test.py`) and pairs of (the visible
    test as given, the spec-consistent test), each in a fresh container; a disagreement is run again."""
    checks = {"official": sandbox.run_check(after_files), "pairs": []}
    sol = solution_files(after_files, rule_set)
    for _ in range(confirm_runs):
        pair = []
        for test in (task["test"], task["original_test"]):
            nonce = secrets.token_hex(8)
            r = sandbox.run_check({**sol, "test.py": tasks.test_file(test, task["entry_point"], nonce).encode()},
                                  nonce=nonce)
            r["passed_strict"] = r["passed"] and r["nonce_seen"]
            r["nonce"] = nonce
            pair.append(r)
        checks["pairs"].append(pair)
        if not (pair[0]["passed_strict"] and not pair[1]["passed_strict"]):
            break
    return checks


def one(task, variant, model, backend_factory, recorder, rule_set, rules_sha, out, opts):
    rid = f"{model.split('/')[-1]}__{variant}__{task['task_id']}"
    outdir = os.path.join(out, rid)
    if os.path.exists(os.path.join(outdir, "verdict.json")):
        return rid, "done before"
    os.makedirs(outdir, exist_ok=True)
    files = tasks.workspace(task)
    task_text = tasks.INSTRUCTION
    before_tar = sandbox.make_tar(files)
    box = sandbox.Sandbox(re.sub(r"[^a-z0-9]+", "-", rid.lower())[:40], opts.time_limit + 300)
    backend = backend_factory(model)
    result = {"status": "error"}
    run = None
    try:
        box.start(files)
        net = {"before": box.net_counters()}
        run = recorder.start(rid, task_text)
        system = agent.SYSTEM.format(instruction=tasks.INSTRUCTION, max_attempts=opts.max_attempts)
        try:
            result = agent.rollout(backend, box, run, task_text, system, max_steps=opts.max_steps,
                                   max_attempts=opts.max_attempts, time_limit_s=opts.time_limit)
        except SignerMissing:
            raise
        except Exception as e:   # the model API or the sandbox failed: the evidence so far is still judged
            result = {"status": "error", "error": f"{type(e).__name__}: {e}"[:2000]}
        net["after"] = box.net_counters()
        after_tar = box.stop_and_snapshot()
    finally:
        box.remove()
    evidence = recorder.finish(run, outdir, rid)
    with open(os.path.join(outdir, "before.tar"), "wb") as f:
        f.write(before_tar)
    with open(os.path.join(outdir, "after.tar"), "wb") as f:
        f.write(after_tar)
    before, after = sandbox.read_tar(before_tar, root=""), sandbox.read_tar(after_tar)
    checks = hidden_checks(task, sandbox.files_of(after), rule_set, rule_set["rules"]["R3"]["confirm_runs"])
    write_json(os.path.join(outdir, "transcript.json"), backend.transcript())
    write_json(os.path.join(outdir, "meta.json"), {"rollout_id": rid, "task_id": task["task_id"], "variant": variant,
                                                    "model": model, "result": result, "usage": backend.usage})
    pins = {"signed": evidence["signed"], "run_id": evidence["run_id"], "bundle": evidence.get("bundle"),
            "bundle_sha256": evidence["bundle_sha256"], "opening": evidence.get("opening"),
            "opening_sha256": evidence.get("opening") and
            sha(open(os.path.join(outdir, evidence["opening"]), "rb").read()),
            "before_sha256": sha(before_tar), "after_sha256": sha(after_tar),
            "checks_sha256": write_json(os.path.join(outdir, "checks.json"), checks),
            "net_sha256": write_json(os.path.join(outdir, "net.json"), net)}
    v = rules.verdict(rule_set, rules_sha, rid, evidence["trace"], before, after, checks, net, pins)
    v["signed"] = evidence["signed"]
    record = recorder.record_verdict(v, outdir)
    write_json(os.path.join(outdir, "verdict.record.json"), record)
    write_json(os.path.join(outdir, "verdict.json"), v)
    return rid, f"{result['status']}; pass={v['passed']} flags={v['classes']}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="referee.run")
    ap.add_argument("--backend", choices=["anthropic", "mlx"], required=True)
    ap.add_argument("--models", required=True, help="comma-separated model ids")
    ap.add_argument("--variants", default=",".join(tasks.VARIANTS))
    ap.add_argument("--n", type=int, default=30, help="tasks per variant")
    ap.add_argument("--seed", type=int, default=20261104)
    ap.add_argument("--max-usd", type=float, default=None, help="hard cap on estimated API spend (required for anthropic)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--time-limit", type=int, default=900, help="seconds per rollout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--unsigned-smoke", action="store_true",
                    help=f"local model only, at most {SMOKE_MAX} rollouts, unsigned stand-in recorder")
    opts = ap.parse_args(argv)
    models, variants = opts.models.split(","), opts.variants.split(",")
    rule_set, rules_sha = rules.load_rules(os.path.join(ROOT, "rules.yaml"))
    pre_sha, pre_commit = prereg()
    jobs = [(t, v, m) for m in models for v in variants
            for t in tasks.load(os.path.join(ROOT, "data", "tasks"), v, opts.n, opts.seed)]
    if opts.backend == "anthropic" and not opts.unsigned_smoke:
        if opts.max_usd is None:
            sys.exit("--max-usd is required with the anthropic backend")
        approved, spent = approved_usd(), ledger_spent()
        if approved is None:
            sys.exit(f"no approved API budget: the owner writes the approved total in dollars to {APPROVED}")
        if spent + opts.max_usd > approved + 1e-9:
            sys.exit(f"refusing to run: ${spent:.2f} spent so far plus --max-usd ${opts.max_usd:.2f} would pass the "
                     f"approved ${approved:.2f}; lower --max-usd to at most ${max(approved - spent, 0):.2f}, or ask the "
                     f"owner to approve the next $50 step in {APPROVED}")
    if opts.unsigned_smoke:
        if opts.backend != "mlx" or len(jobs) > SMOKE_MAX:
            sys.exit(f"--unsigned-smoke: local model only, at most {SMOKE_MAX} rollouts ({len(jobs)} asked)")
        recorder = FakeRecorder()
    else:
        if pre_sha != rules_sha:
            sys.exit(f"rules.yaml (sha256 {rules_sha}) is not the one docs/prereg.md fixes ({pre_sha}): a signed run "
                     "uses the pre-registered rules only")
        try:
            recorder = TracekitRecorder(ROOT)
        except SignerMissing as e:
            sys.exit(f"refusing to run: {e}")
    if opts.backend == "anthropic":
        try:
            agent.keychain_key()
        except agent.KeyMissing as e:
            sys.exit(str(e))
        budget = agent.Budget(opts.max_usd)
        factory = lambda m: agent.AnthropicBackend(m, budget)   # noqa: E731
    else:
        loaded = {}   # one model in memory, one rollout at a time

        def factory(m):
            if m not in loaded:
                loaded[m] = agent.MLXBackend(m)
            return loaded[m]
        opts.workers = 1
    os.makedirs(opts.out, exist_ok=True)
    write_json(os.path.join(opts.out, "manifest.json"), {
        "backend": opts.backend, "models": models, "variants": variants, "n": opts.n, "seed": opts.seed,
        "max_usd": opts.max_usd, "rules_sha256": rules_sha, "prereg_rules_sha256": pre_sha,
        "prereg_commit": pre_commit, "signed": recorder.signed, "max_steps": opts.max_steps,
        "max_attempts": opts.max_attempts, "time_limit_s": opts.time_limit,
        "head": subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    stop = threading.Event()

    def job(t, v, m):
        if stop.is_set():
            return None
        try:
            rid, msg = one(t, v, m, factory, recorder, rule_set, rules_sha, opts.out, opts)
        except SignerMissing as e:
            stop.set()
            return f"STOP (no unsigned evidence): {e}"
        except Exception:
            return f"{m} {v} {t['task_id']}: FAILED\n{traceback.format_exc()[-1500:]}"
        if "budget" in msg:
            stop.set()
        return f"{rid}: {msg}"

    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"
    if opts.backend == "anthropic":
        ledger_add(run_id, "reserved", opts.max_usd, opts.out, models)
    try:
        with concurrent.futures.ThreadPoolExecutor(opts.workers) as ex:
            for line in ex.map(lambda j: job(*j), jobs):
                if line:
                    print(line, flush=True)
    finally:
        if opts.backend == "anthropic":
            ledger_add(run_id, "settled", budget.spent, opts.out, models)
            total, approved = ledger_spent(), approved_usd()
            print(f"estimated API spend: this run ${budget.spent:.4f} of its ${opts.max_usd:.2f} cap; all runs "
                  f"${total:.4f} of the approved ${approved:.2f}; remaining ${approved - total:.4f}")
    return 1 if stop.is_set() else 0


if __name__ == "__main__":
    sys.exit(main())
