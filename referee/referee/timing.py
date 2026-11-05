"""Where a run's time goes, from the signed timestamps in its bundles (read-only).

    .venv/bin/python -m referee.timing runs/pilot

Per rollout: model time (from each tool result, or the run's start, to the next decision), tool time (decision to
result), the signer's close (closing to final), and the harness's tail (the agent run's final record to the verdict
run's last record: export, opening, hidden checks, verdict). Then the run's throughput.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import statistics
import sys

from tracekit.verify.v2 import read_zip


def _events(bundle):
    files = read_zip(bundle)
    return [json.loads(line)["event"] for n, data in files.items() if n.startswith("runs/")
            for line in data.decode().splitlines()]


def _ts(e):
    return datetime.datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp()


def rollout_times(d):
    ev = sorted(_events(os.path.join(d, "rollout.tkb")), key=lambda e: e["run_seq"])
    start = _ts(ev[0])
    model = tool = 0.0
    last = start
    for e in ev:
        if e["type"] == "policy.decision":
            model += _ts(e) - last
        elif e["type"] == "tool.result":
            tool += _ts(e) - last
        if e["type"] in ("policy.decision", "tool.result"):
            last = _ts(e)
    closing = next(_ts(e) for e in ev if e["type"] == "run.closing")
    final = next(_ts(e) for e in ev if e["type"] == "run.final")
    model += closing - last   # the last model turn, which ended without a tool call or after submit
    verdict_end = max(_ts(e) for e in _events(os.path.join(d, "verdict.tkb")))
    return {"start": start, "end": verdict_end, "model": model, "tool": tool, "signer_close": final - closing,
            "tail": verdict_end - final, "wall": verdict_end - start, "calls": sum(e["type"] == "tool.result"
                                                                                   for e in ev)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="referee.timing")
    ap.add_argument("run_dir")
    a = ap.parse_args(argv)
    rows = collections.defaultdict(list)
    allr = []
    for v in sorted(glob.glob(os.path.join(a.run_dir, "*", "verdict.tkb"))):
        d = os.path.dirname(v)
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)
        t = rollout_times(d)
        rows[(meta["model"], meta["variant"])].append(t)
        allr.append(t)
    if not allr:
        sys.exit("no finished signed rollouts")

    def med(xs):
        return round(statistics.median(xs), 1)
    print("cell (model, variant): n, median seconds: wall, model, tool, signer close, harness tail; tool calls")
    for k, ts in sorted(rows.items()):
        print(f"  {k}: {len(ts)}, wall {med([t['wall'] for t in ts])}, model {med([t['model'] for t in ts])}, "
              f"tool {med([t['tool'] for t in ts])}, close {med([t['signer_close'] for t in ts])}, "
              f"tail {med([t['tail'] for t in ts])}; calls {med([t['calls'] for t in ts])}")
    span = max(t["end"] for t in allr) - min(t["start"] for t in allr)
    busy = sum(t["wall"] for t in allr)
    total = {k: sum(t[k] for t in allr) for k in ("model", "tool", "signer_close", "tail")}
    print(f"all {len(allr)} rollouts: {span / 60:.1f} min elapsed, {len(allr) / (span / 3600):.1f} rollouts/hour, "
          f"{busy / span:.2f} rollouts in flight on average")
    print("share of rollout time: " + ", ".join(f"{k} {v / busy:.0%}" for k, v in total.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
