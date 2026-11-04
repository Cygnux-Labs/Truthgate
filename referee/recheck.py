"""Re-check a rollout's verdict from its evidence alone.

    .venv/bin/python -I -m referee.recheck runs/pilot/<rollout> [--trust signer-data/trust.json] [--rerun-hidden]

It verifies the rollout bundle against the pinned signer key, opens every recorded call against its signed
commitment, checks the hashes the verdict pins, recomputes the verdict with rules.yaml, and checks that the signed
verdict event holds that same verdict. `--rerun-hidden` also runs the hidden checks again in fresh containers.
"""
import argparse
import hashlib
import json
import os
import sys

from referee import rules, sandbox
from referee.recorder import bundle_events, build_trace
from referee.run import ROOT, hidden_checks

from tracekit.format.canon import canonical


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def evidence(d, trust):
    """(verdict, trace, before, after, checks, net, problems) of a rollout dir, each input checked against the hashes
    the verdict pins, the trace opened against its signed commitments."""
    problems = []
    with open(os.path.join(d, "verdict.json")) as f:
        v = json.load(f)
    pins = v["evidence"]
    for name, key in (("before.tar", "before_sha256"), ("after.tar", "after_sha256"), ("checks.json", "checks_sha256"),
                      ("net.json", "net_sha256")):
        if _sha(os.path.join(d, name)) != pins[key]:
            problems.append(f"{name} does not hash to the verdict's {key}")
    if v.get("signed"):
        if _sha(os.path.join(d, pins["bundle"])) != pins["bundle_sha256"]:
            problems.append("rollout.tkb does not hash to the verdict's bundle_sha256")
        if _sha(os.path.join(d, pins["opening"])) != pins["opening_sha256"]:
            problems.append("opening.json does not hash to the verdict's opening_sha256")
        rep, events = bundle_events(os.path.join(d, pins["bundle"]), trust, pins["run_id"])
        if rep.integrity != "VERIFIED":
            problems.append(f"rollout bundle: {rep.integrity} ({', '.join(rep.failures)})")
        with open(os.path.join(d, pins["opening"])) as f:
            trace = build_trace(events, json.load(f)["items"])   # raises TraceMismatch on a bad opening
    else:
        problems.append("UNSIGNED: smoke evidence, no bundle to verify")
        with open(os.path.join(d, "trace.unsigned.json")) as f:
            trace = json.load(f)
    with open(os.path.join(d, "before.tar"), "rb") as f:
        before = sandbox.read_tar(f.read(), root="")
    with open(os.path.join(d, "after.tar"), "rb") as f:
        after = sandbox.read_tar(f.read())
    with open(os.path.join(d, "checks.json")) as f:
        checks = json.load(f)
    with open(os.path.join(d, "net.json")) as f:
        net = json.load(f)
    return v, trace, before, after, checks, net, problems


def compare_rules(d, trust, rules_a, rules_b):
    """(classes under rules_a, classes under rules_b, passed) of one rollout, recomputed from its evidence; writes
    nothing."""
    v, trace, before, after, checks, net, _ = evidence(d, trust)
    out = []
    for path in (rules_a, rules_b):
        rule_set, sha = rules.load_rules(path)
        out.append(rules.verdict(rule_set, sha, v["rollout_id"], trace, before, after, checks, net,
                                 v["evidence"])["classes"])
    return out[0], out[1], v["passed"]


def recheck(d, trust, rules_path, rerun_hidden=False):
    v, trace, before, after, checks, net, problems = evidence(d, trust)
    pins = v["evidence"]
    rule_set, rules_sha = rules.load_rules(rules_path)
    if rules_sha != v["rules_sha256"]:
        problems.append(f"rules.yaml is {rules_sha}, the verdict used {v['rules_sha256']}")
    again = rules.verdict(rule_set, rules_sha, v["rollout_id"], trace, before, after, checks, net, pins)
    again["signed"] = v.get("signed")
    if "rescored_from" in v:
        again["rescored_from"] = v["rescored_from"]
    if canonical(json.loads(json.dumps(again, default=str))) != canonical(v):
        problems.append("the recomputed verdict differs from verdict.json")
    if v.get("signed"):
        with open(os.path.join(d, "verdict.record.json")) as f:
            rec = json.load(f)
        if not rec.get("signed"):
            problems.append("the verdict was not recorded as a signed event")
        else:
            if _sha(os.path.join(d, rec["bundle"])) != rec["bundle_sha256"]:
                problems.append("verdict.tkb does not hash to verdict.record.json")
            rep, events = bundle_events(os.path.join(d, rec["bundle"]), trust, rec["run_id"])
            if rep.integrity != "VERIFIED":
                problems.append(f"verdict bundle: {rep.integrity}")
            with open(os.path.join(d, "verdict.opening.json")) as f:
                signed = build_trace(events, json.load(f)["items"])
            call = next((c for c in signed if c["tool"] == "referee.verdict"), None)
            if not call or call["args_opened"] != "opened" or canonical(call["args"]["verdict"]) != canonical(v):
                problems.append("the signed verdict event does not hold verdict.json")
    if rerun_hidden:
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)
        task = next(t for t in map(json.loads, open(os.path.join(ROOT, "data", "tasks", f"{meta['variant']}.jsonl")))
                    if t["task_id"] == meta["task_id"])
        fresh = hidden_checks(task, sandbox.files_of(after), rule_set, rule_set["rules"]["R3"]["confirm_runs"])
        bits = lambda c: (c["official"]["passed"], [[x["passed_strict"] for x in p] for p in c["pairs"]])  # noqa: E731
        if bits(fresh) != bits(checks):
            problems.append(f"hidden checks re-run differently: {bits(fresh)} vs recorded {bits(checks)}")
    return v, problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="referee.recheck")
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--trust", default=os.path.join(ROOT, "signer-data", "trust.json"))
    ap.add_argument("--rules", default=os.path.join(ROOT, "rules.yaml"))
    ap.add_argument("--rerun-hidden", action="store_true")
    ap.add_argument("--compare-rules", metavar="RULES",
                    help="recompute each verdict under --rules and under RULES and list every rollout whose classes "
                         "differ (writes nothing)")
    a = ap.parse_args(argv)
    if a.compare_rules:
        same = 0
        for d in a.dirs:
            old, new, passed = compare_rules(d, a.trust, a.rules, a.compare_rules)
            if old == new:
                same += 1
            else:
                print(f"{os.path.basename(os.path.normpath(d))} (pass={passed}): {old} -> {new}")
        print(f"{same} of {len(a.dirs)} rollouts keep their classes")
        return 0
    bad = 0
    for d in a.dirs:
        v, problems = recheck(d, a.trust, a.rules, a.rerun_hidden)
        hard = [p for p in problems if not p.startswith("UNSIGNED")]
        bad += bool(hard)
        print(f"{'SAME VERDICT' if not hard else 'MISMATCH'} {v['rollout_id']}: classes {v['classes']}"
              + "".join(f"\n  - {p}" for p in problems))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
