"""The API spend ledger (runs/spend-ledger.tsv) and the owner-approved total (runs/approved-usd.txt).

    .venv/bin/python -m referee.ledger show
    .venv/bin/python -m referee.ledger settle RUN_ID --from-dir runs/pilot   # a run killed before it settled
    .venv/bin/python -m referee.ledger approve-next                         # the owner: the next $50 step

A run that never settled counts at its whole cap. `settle` replaces that with what its rollouts or judge calls
recorded they spent (the same token-cost estimates the run itself settles with).
"""
import argparse
import glob
import json
import os
import sys

from referee import run

STEP = 50.0


def rows():
    try:
        with open(run.LEDGER) as f:
            return [line.rstrip("\n").split("\t") for line in f.readlines()[1:] if line.strip()]
    except FileNotFoundError:
        return []


def recorded_usd(run_dir):
    """What a run's outputs say it spent: each rollout's meta.json usage and its final-report turn, or each judge
    record's usd. A rollout killed mid-episode (its directory, no meta.json) recorded nothing, so it counts at the mean
    of the finished ones.
    lean: an estimate for killed rollouts, below the truth when one was a long episode; use the API's usage report if a
    settle must be exact."""
    total, done = 0.0, 0
    for p in glob.glob(os.path.join(run_dir, "*", "meta.json")):
        with open(p) as f:
            total += json.load(f).get("usage", {}).get("usd", 0.0)
        done += 1
    for p in glob.glob(os.path.join(run_dir, "*", "final_report.json")):
        with open(p) as f:
            total += json.load(f).get("usd") or 0.0
    killed = [d for d in glob.glob(os.path.join(run_dir, "*__*")) if os.path.isdir(d)
              and not os.path.exists(os.path.join(d, "meta.json"))]
    if killed and done:
        total += len(killed) * total / done
    for p in glob.glob(os.path.join(run_dir, "*.llm-*.json")):
        with open(p) as f:
            total += json.load(f).get("usd") or 0.0
    return total


def show():
    reserved = {r[1]: r for r in rows() if r[2] == "reserved"}
    settled = {r[1]: float(r[3]) for r in rows() if r[2] == "settled"}
    for rid, r in reserved.items():
        state = f"settled ${settled[rid]:.4f}" if rid in settled else f"OPEN: counted at its ${float(r[3]):.2f} cap"
        print(f"{r[0]}  {rid}  {r[4]}  cap ${float(r[3]):.2f}  {state}")
    spent, approved = run.ledger_spent(), run.approved_usd()
    print(f"spent ${spent:.4f}; approved ${approved:.2f}; remaining in this step ${approved - spent:.4f}"
          if approved is not None else f"spent ${spent:.4f}; no approved total in {run.APPROVED}")


def settle(run_id, run_dir):
    reserved = [r for r in rows() if r[1] == run_id and r[2] == "reserved"]
    if not reserved:
        sys.exit(f"no run {run_id} in the ledger")
    if any(r[1] == run_id and r[2] == "settled" for r in rows()):
        sys.exit(f"run {run_id} is settled already")
    usd = recorded_usd(run_dir)
    run.ledger_add(run_id, "settled", usd, reserved[0][4], reserved[0][5].split(","))
    print(f"settled {run_id} at ${usd:.4f}, what {run_dir} records it spent")


def approve_next():
    approved = run.approved_usd()
    if approved is None:
        sys.exit(f"no approved total in {run.APPROVED}")
    with open(run.APPROVED, "w") as f:
        f.write(f"{approved + STEP:g}\n")
    print(f"approved ${approved:.2f} -> ${approved + STEP:.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="referee.ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    p = sub.add_parser("settle")
    p.add_argument("run_id")
    p.add_argument("--from-dir", required=True)
    sub.add_parser("approve-next")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        show()
    elif a.cmd == "settle":
        settle(a.run_id, a.from_dir)
    else:
        approve_next()
    return 0


if __name__ == "__main__":
    sys.exit(main())
