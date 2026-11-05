"""Re-score a finished run with another rules file, from its recorded evidence, into a new run dir.

    .venv/bin/python -m referee.rescore runs/pilot runs/v1/baseline --rules rules-v1.yaml

Study v1's baseline reuses the pilot's rollouts this way. Each rollout's evidence is copied byte for byte (the source
is only read) and checked against the hashes its verdict pins; the verdict is recomputed with the new rules and
recorded as a signed verdict event on the referee's signer, which must be running (`--no-sign` is for tests only).
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys

from referee import rules, run
from referee.recheck import evidence
from referee.recorder import FakeRecorder, SignerMissing, TracekitRecorder

FILES = ("before.tar", "after.tar", "checks.json", "net.json", "opening.json", "rollout.tkb", "transcript.json",
         "trace.unsigned.json")


def rescore(src, dst, rules_name, recorder, trust, condition="baseline"):
    rule_set, sha = rules.load_rules(os.path.join(run.ROOT, rules_name))
    os.makedirs(dst, exist_ok=True)
    if not os.path.exists(os.path.join(dst, "manifest.json")):
        with open(os.path.join(src, "manifest.json")) as f:
            source = json.load(f)
        run.write_json(os.path.join(dst, "manifest.json"), {**source, "rules": rules_name, "rules_sha256": sha,
                                                            "condition": condition, "rescored_from": src})
    lines = []
    for vpath in sorted(glob.glob(os.path.join(src, "*", "verdict.json"))):
        s = os.path.dirname(vpath)
        rid = os.path.basename(s)
        d = os.path.join(dst, rid)
        if os.path.exists(os.path.join(d, "verdict.json")):
            continue
        old, trace, before, after, checks, net, problems = evidence(s, trust)
        bad = [p for p in problems if not p.startswith("UNSIGNED")]
        if bad:
            lines.append(f"{rid}: NOT RESCORED: {'; '.join(bad)}")
            continue
        os.makedirs(d, exist_ok=True)
        for name in FILES:
            if os.path.exists(os.path.join(s, name)):
                shutil.copyfile(os.path.join(s, name), os.path.join(d, name))
        with open(os.path.join(s, "meta.json")) as f:
            meta = json.load(f)
        run.write_json(os.path.join(d, "meta.json"), {**meta, "condition": condition, "rules": rules_name,
                                                      "rescored_from": s})
        v = rules.verdict(rule_set, sha, rid, trace, before, after, checks, net, old["evidence"])
        with open(vpath, "rb") as f:
            v.update(signed=old.get("signed"), rescored_from={
                "verdict_sha256": hashlib.sha256(f.read()).hexdigest(), "rules_sha256": old["rules_sha256"]})
        run.write_json(os.path.join(d, "verdict.record.json"), recorder.record_verdict(v, d))
        run.write_json(os.path.join(d, "verdict.json"), v)
        lines.append(f"{rid}: {old['classes']} -> {v['classes']}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="referee.rescore")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--rules", default="rules-v1.yaml")
    ap.add_argument("--condition", default="baseline")
    ap.add_argument("--trust", default=os.path.join(run.ROOT, "signer-data", "trust.json"))
    ap.add_argument("--no-sign", action="store_true", help="tests only: the new verdicts are not recorded as events")
    a = ap.parse_args(argv)
    if os.path.abspath(a.dst).startswith(os.path.abspath(a.src) + os.sep) or os.path.abspath(a.dst) == \
            os.path.abspath(a.src):
        sys.exit("the destination must be outside the source run")
    if run.prereg(a.rules)[0] != rules.load_rules(os.path.join(run.ROOT, a.rules))[1] or run.code_mismatches(a.rules):
        sys.exit(f"{a.rules} or the referee code is not what {run.PREREGS.get(a.rules)} pins")
    if a.no_sign:
        recorder = FakeRecorder()
    else:
        try:
            recorder = TracekitRecorder(run.ROOT)
        except SignerMissing as e:
            sys.exit(f"refusing to rescore: {e}")
    for line in rescore(a.src, a.dst, a.rules, recorder, a.trust, a.condition):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
