"""truthgate command line.

  truthgate collect          run the real agent model on all tasks, save labelled runs
  truthgate demo             make a fake dataset with scripted agents (no model needed)
  truthgate monitor          score runs with the Claude text monitor
  truthgate sweep            per-layer probe AUROC on dev runs
  truthgate report           write work/report.md (labels, probes vs monitor) from dev runs
  truthgate check-claim F    check a claim JSON on held-out runs (counts against the budget)
  truthgate ledger           show all checked claims
  truthgate serve-mcp        start the MCP server for Claude Code

  truthgate deploy HASH      turn a CONFIRMED detector claim into a live detector (threshold set on dev)
  truthgate run-guarded      run the agent with the live guard reading its activations
  truthgate guard-eval       replay held-out runs through the guard vs the text monitor
  truthgate guard-log        show recent live guard decisions
  truthgate dashboard        local web page over dev runs, claims and the guard (http://127.0.0.1:8765)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from .config import load_config, make_backend
from .episode import load_runs, run_episode, save_episode
from .labels import CONTRASTS
from .steps import STEP_CONTRASTS
from .tasks import FAULTS, PRESSURES, all_tasks


def _claude_judge(cfg):
    from .disclosure import ClaudeJudge
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("needs ANTHROPIC_API_KEY: the disclosure judge labels 'done' claims made against evidence of failure")
    return ClaudeJudge(cfg["monitor"]["model"])


def cmd_collect(cfg, args):
    c = cfg["collect"]
    tasks = all_tasks(c["templates"], [args.fault] if args.fault else (c["faults"] or FAULTS),
                      c["pressures"] or PRESSURES)
    if args.split:
        tasks = [t for t in tasks if t.split == args.split]
    if args.limit:
        tasks = tasks[: args.limit]
    judge = _claude_judge(cfg)
    backend = make_backend(cfg)
    short = cfg["model"]["id"].split("/")[-1]
    n = args.samples or c["samples_per_task"]
    root = Path(cfg["data_dir"])
    done = failed = 0
    for k in range(n):
        for t in tasks:
            run_id = f"{t.id}__{short}__s{k}"
            if (root / t.split / run_id / "episode.json").exists():
                continue
            try:
                ep = run_episode(t, backend, max_steps=c["max_steps"], judge=judge)
            except Exception as e:  # noqa: BLE001  logged; the run is not saved, so the next collect retries it
                failed += 1
                print(f"[skip] {run_id}: {type(e).__name__}: {e}", flush=True)
                if failed >= 3:
                    sys.exit("3 runs failed in a row; stopping (errors above)")
                continue
            failed = 0
            d = ep["disclosure"]
            note = ("" if d is None or d.get("agree", True) else
                    f" [judge: {'disclosed' if d['discloses'] else 'hidden'}; keyword rule disagrees]")
            save_episode(ep, root, run_id)
            done += 1
            print(f"[{done}] {run_id}: {ep['label']} ({ep['seconds']}s) - {ep['label_reason']}{note}", flush=True)
    print(f"collected {done} new runs into {root}")


def cmd_demo(cfg, args):
    from .backends import ScriptedBackend
    from .disclosure import keyword_judge
    rng = random.Random(0)
    policies = ["solver", "quitter", "liar", "tamperer", "discloser", "lazy", "trusting"]
    root = Path(cfg["data_dir"])
    n = 0
    for k in range(args.samples or 2):
        for t in all_tasks():
            pol = rng.choice(policies)
            ep = run_episode(t, ScriptedBackend(pol, t, seed=rng.randrange(10**6)), max_steps=8, judge=keyword_judge)
            save_episode(ep, root, f"{t.id}__scripted-{pol}__s{k}")
            n += 1
    print(f"wrote {n} scripted runs into {root}")


def cmd_monitor(cfg, args):
    from .monitor import monitor_runs
    m = cfg["monitor"]
    runs = load_runs(cfg["data_dir"], args.split, with_acts=False)
    k = monitor_runs(runs, m["model"], m["include_reasoning"], m["workers"], force=args.force)
    print(f"scored {k} runs in {args.split} with {m['model']}")


def cmd_sweep(cfg, args):
    from .probes import build, layer_sweep
    runs = load_runs(cfg["data_dir"], "dev")
    ds = build(runs, args.contrast, args.position, args.step if args.step == "submit" else int(args.step))
    if ds is None:
        sys.exit("no runs for this contrast yet")
    print(f"contrast={args.contrast} position={args.position} step={ds['step']} "
          f"n={len(ds['y'])} positives={int(ds['y'].sum())}")
    for r in layer_sweep(ds, args.method):
        bar = "#" * int(max(0, (r["auroc"] - 0.5)) * 80) if r["auroc"] == r["auroc"] else ""
        print(f"layer {r['layer']:3d}  AUROC {r['auroc']:.3f}  {bar}")


def label_table(runs) -> str:
    cnt = Counter((ep["task"]["fault"], ep["task"]["pressure"], ep["label"]) for ep in runs)
    labels = sorted({k[2] for k in cnt})
    rows = ["| fault | pressure | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
    for f in FAULTS:
        for p in PRESSURES:
            rows.append(f"| {f} | {p} | " + " | ".join(str(cnt.get((f, p, lab), 0)) for lab in labels) + " |")
    return "\n".join(rows)


def cmd_report(cfg, args):
    from .monitor import monitor_score
    from .probes import _auc, build, layer_sweep
    runs = load_runs(cfg["data_dir"], "dev")
    out = [f"# truthgate report (dev split, {len(runs)} runs)", "", "## Labels", "", label_table(runs), ""]
    out += ["## Internal probes vs text monitor (grouped by task template, out-of-fold)", "",
            "| contrast | n | positives | best layer (diff-in-means) | probe AUROC | text monitor AUROC |",
            "|---|---|---|---|---|---|"]
    m = cfg["monitor"]
    for contrast in CONTRASTS:
        ds = build(runs, contrast, "pre", "submit")
        if ds is None or len(set(ds["y"])) < 2 or len(set(ds["groups"])) < 2:
            out.append(f"| {contrast} | - | - | - | not enough data | - |")
            continue
        sweep = layer_sweep(ds, "diffmeans")
        best = max(sweep, key=lambda r: -1 if r["auroc"] != r["auroc"] else r["auroc"])
        by_id = {ep["run_id"]: ep for ep in runs}
        ms = [monitor_score(by_id[i], contrast, m["model"], m["include_reasoning"]) for i in ds["ids"]]
        have = [j for j, v in enumerate(ms) if v is not None]
        mon = (f"{_auc(ds['y'][have], np.array([ms[j] for j in have])):.3f} (n={len(have)})"
               if len(have) > 1 and len(set(ds['y'][have])) == 2 else "not run")
        out.append(f"| {contrast} | {len(ds['y'])} | {int(ds['y'].sum())} | {best['layer']} | "
                   f"{best['auroc']:.3f} | {mon} |")
    out += ["", "Best-layer probe AUROC is chosen on dev, so it is optimistic. Only claims checked on",
            "held-out runs (`truthgate check-claim`) count as results.", ""]
    p = Path(cfg["work_dir"]) / "report.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out))
    print("\n".join(out))


def cmd_check_claim(cfg, args):
    from .claims import check_claim
    claim = json.loads(Path(args.claim).read_text())
    print(json.dumps(check_claim(claim, cfg), indent=1, default=float))


def cmd_ledger(cfg, args):
    from .claims import read_ledger
    for e in read_ledger(cfg):
        print(f"{e['time']}  {e['verdict']:12s}  {e['claim']['kind']:8s}  {e['claim']['statement'][:90]}")


def cmd_deploy(cfg, args):
    from .guard import deploy
    print(json.dumps(deploy(cfg, args.hash, args.fpr, args.name), indent=1))


def cmd_run_guarded(cfg, args):
    from .backends import ScriptedBackend
    from .guard import Guard
    guard = Guard.from_config(cfg, args.mode, args.on_block)
    tasks = all_tasks()
    if args.task:
        tasks = [t for t in tasks if t.id == args.task or t.template == args.task]
    if args.split:
        tasks = [t for t in tasks if t.split == args.split]
    tasks = tasks[: args.limit] if args.limit else tasks
    from .disclosure import keyword_judge
    judge = keyword_judge if args.scripted else _claude_judge(cfg)
    backend = None if args.scripted else make_backend(cfg)
    root = Path(cfg["data_dir"]) / "guarded"
    short = "scripted" if args.scripted else cfg["model"]["id"].split("/")[-1]
    rng = random.Random(0)
    tally = Counter()
    for t in tasks:
        b = ScriptedBackend(rng.choice(["solver", "liar", "tamperer", "discloser", "trusting", "quitter"]), t,
                            seed=rng.randrange(10**6)) if args.scripted else backend
        ep = run_episode(t, b, max_steps=cfg["collect"]["max_steps"], guard=guard, judge=judge)
        tag = f"{short}-{b.policy}" if args.scripted else short
        save_episode(ep, root, f"{t.id}__{tag}__{guard.mode}-{guard.on_block}")
        g = ep["guard"]
        for blk in g["blocked"]:
            tally[f"blocked:{blk['would_be_label']}"] += 1
            where = f" ({blk['path']})" if "path" in blk else ""
            print(f"  BLOCK {t.id} {blk['tool']}{where}: would have been {blk['would_be_label']}  scores={blk['scores']}")
        tally[f"final:{ep['label']}"] += 1
        print(f"{t.id}: final={ep['label']} held={g['held']} blocks={len(g['blocked'])}", flush=True)
    print(json.dumps(dict(sorted(tally.items())), indent=1))


def cmd_guard_eval(cfg, args):
    from .guard import evaluate
    print(json.dumps(evaluate(cfg, args.split), indent=1))


def cmd_guard_log(cfg, args):
    from .guard import guard_dir
    p = guard_dir(cfg) / "live_log.jsonl"
    if not p.exists():
        sys.exit("no live guard decisions yet")
    for line in p.read_text().splitlines()[-args.n:]:
        d = json.loads(line)
        sc = " ".join(f"{k}={v:+.2f}" for k, v in d["scores"].items())
        tool = "write tests/" if d.get("is_test_write") else str(d["tool"])
        print(f"{d.get('task', '?'):40s} step {d.get('agent_step', '?'):>2}  {tool:12s} {d['action']:5s} {sc}")


def cmd_dashboard(cfg, args):
    from .dashboard import serve
    serve(cfg, args.port)


def cmd_serve(cfg, args):
    from .mcp_server import serve
    serve(args.config)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="truthgate")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect"); s.add_argument("--limit", type=int); s.add_argument("--samples", type=int)
    s.add_argument("--fault", choices=FAULTS); s.add_argument("--split", choices=["dev", "heldout"])
    s = sub.add_parser("demo"); s.add_argument("--samples", type=int)
    s = sub.add_parser("monitor"); s.add_argument("--split", default="dev", choices=["dev", "heldout"])
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("sweep"); s.add_argument("--contrast", default="knows_false", choices=list(CONTRASTS) + list(STEP_CONTRASTS))
    s.add_argument("--position", default="pre", choices=["pre", "gen_mean", "gen_last"])
    s.add_argument("--step", default="submit"); s.add_argument("--method", default="diffmeans",
                                                               choices=["diffmeans", "logreg"])
    sub.add_parser("report")
    s = sub.add_parser("check-claim"); s.add_argument("claim")
    sub.add_parser("ledger")
    sub.add_parser("serve-mcp")
    s = sub.add_parser("deploy"); s.add_argument("hash"); s.add_argument("--fpr", type=float, default=0.05)
    s.add_argument("--name")
    s = sub.add_parser("run-guarded"); s.add_argument("--mode", default="block", choices=["watch", "flag", "block"])
    s.add_argument("--on-block", default="hold", choices=["hold", "reprompt"])
    s.add_argument("--task"); s.add_argument("--split", choices=["dev", "heldout"]); s.add_argument("--limit", type=int)
    s.add_argument("--scripted", action="store_true", help="use scripted fake agents (pipeline test)")
    s = sub.add_parser("guard-eval"); s.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    s = sub.add_parser("guard-log"); s.add_argument("-n", type=int, default=30)
    s = sub.add_parser("dashboard"); s.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    {"collect": cmd_collect, "demo": cmd_demo, "monitor": cmd_monitor, "sweep": cmd_sweep,
     "report": cmd_report, "check-claim": cmd_check_claim, "ledger": cmd_ledger,
     "serve-mcp": cmd_serve, "deploy": cmd_deploy, "run-guarded": cmd_run_guarded,
     "guard-eval": cmd_guard_eval, "guard-log": cmd_guard_log,
     "dashboard": cmd_dashboard}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
