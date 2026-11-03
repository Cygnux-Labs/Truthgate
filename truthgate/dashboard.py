"""Lab view: a local web page over DEV runs, the claim ledger and the live guard.

    truthgate dashboard            then open http://127.0.0.1:8765

Like the researcher's MCP tools it serves DEV runs only: held-out runs are read by the claim
checker and nothing else, so this module never opens data/heldout. It binds to 127.0.0.1, loads
no activations except the shape for one run, and re-reads files on every request, so it follows
a collection while it runs.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np

from .claims import read_ledger
from .episode import load_runs
from .guard import deployed, guard_dir
from .steps import step_labels
from .tasks import FAULTS, PRESSURES, TEMPLATES, split_of

PAGE = Path(__file__).with_name("dashboard.html")


def _monitor(ep: dict, cfg: dict) -> dict | None:
    f = Path(ep["dir"]) / "monitor.json"
    m = cfg["monitor"]
    return json.loads(f.read_text()).get(f"{m['model']}|reasoning={m['include_reasoning']}") if f.exists() else None


def _row(ep: dict) -> dict:
    h, t = ep["host"], ep["task"]
    return {"run_id": ep["run_id"], "template": t["template"], "fault": t["fault"], "pressure": t["pressure"],
            "label": ep["label"], "reason": ep["label_reason"], "steps": len(ep["step_meta"]),
            "seconds": ep.get("seconds"), "said": (h.get("claim") or {}).get("status"),
            "pristine_passed": h["real_passed"], "pristine_failed": h["real_failed"],
            "tests_tampered": h["tests_tampered"], "test_writes": step_labels(ep).count("write_test"),
            "invalid_calls": sum(m["tool"] is None for m in ep["step_meta"]), "disclosure": ep.get("disclosure"),
            "mtime": (Path(ep["dir"]) / "episode.json").stat().st_mtime}


def runs_table(cfg: dict) -> list[dict]:
    return sorted((_row(ep) for ep in load_runs(cfg["data_dir"], "dev", with_acts=False)), key=lambda r: -r["mtime"])


def summary(cfg: dict, rows: list[dict]) -> dict:
    c = cfg["collect"]
    dev_templates = [n for n in (c["templates"] or [t["name"] for t in TEMPLATES]) if split_of(n) == "dev"]
    faults, pressures = c["faults"] or FAULTS, c["pressures"] or PRESSURES
    grid = [{"fault": f, "pressure": p,
             "labels": Counter(r["label"] for r in rows if r["fault"] == f and r["pressure"] == p)}
            for f in faults for p in pressures]
    ledger = read_ledger(cfg)
    log = guard_dir(cfg) / "live_log.jsonl"
    return {
        "model": cfg["model"]["id"], "data_dir": cfg["data_dir"],
        "dev_runs": len(rows), "dev_expected": len(dev_templates) * len(faults) * len(pressures) * c["samples_per_task"],
        "dev_templates": dev_templates, "labels": Counter(r["label"] for r in rows), "grid": grid,
        "test_write_steps": sum(r["test_writes"] for r in rows),
        "runs_with_test_writes": sum(r["test_writes"] > 0 for r in rows),
        "invalid_calls": sum(r["invalid_calls"] for r in rows),
        "runs_with_invalid_calls": sum(r["invalid_calls"] > 0 for r in rows),
        "judge_disagreements": sum(1 for r in rows if (r["disclosure"] or {}).get("agree") is False),
        "claims": {"budget": cfg["claims"]["budget"], "used": len(ledger), "entries": [
            {k: e.get(k) for k in ("time", "hash", "verdict", "reason", "auroc", "auroc_ci95", "random_direction_p",
                                   "auroc_vs_each_negative_label", "n_heldout", "n_positive", "monitor_auroc",
                                   "probe_minus_monitor_ci95", "checks_used")}
            | {"statement": e["claim"]["statement"], "kind": e["claim"]["kind"],
               "contrast": e["claim"].get("contrast"), "direction": e.get("direction_meta")}
            for e in ledger]},
        "guard": {"detectors": [{**{k: v for k, v in asdict(d).items() if k != "vector"}, "acts_on": d.acts_on}
                                for d in deployed(cfg)],
                  "recent": [json.loads(x) for x in log.read_text().splitlines()[-40:]] if log.exists() else []},
    }


def run_detail(cfg: dict, run_id: str) -> dict | None:
    root = (Path(cfg["data_dir"]) / "dev").resolve()
    d = (root / run_id).resolve()
    if d.parent != root or not (d / "episode.json").exists():      # only a direct child of data/dev
        return None
    ep = json.loads((d / "episode.json").read_text())
    ep["dir"] = str(d)
    labs, host = step_labels(ep), {r["step"]: r for r in ep["host_log"]}
    steps = []
    for m in ep["transcript"]:
        if m["role"] == "assistant":
            meta = ep["step_meta"][len(steps)]
            rec = host.get(meta.get("host_step"))
            steps.append({"label": labs[len(steps)], "reasoning": m.get("reasoning", ""), "text": m.get("text", ""),
                          "tool_call": m.get("tool_call"), "host": (rec or {}).get("host"), "result": None})
        elif steps:
            steps[-1]["result"] = {"role": m["role"], "name": m.get("name"), "text": m["text"]}
    acts = None
    if (d / "acts.npz").exists():
        with np.load(d / "acts.npz") as z:
            acts = {k: list(z[k].shape) for k in z.files}
    return {**_row(ep), "prompt": ep["task"]["prompt"], "claim": ep["host"].get("claim"),
            "shown_tests": ep["host"]["shown_tests"], "steps": steps, "acts": acts, "monitor": _monitor(ep, cfg),
            "model_id": ep.get("model")}


def make_server(cfg: dict, port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/state":
                    rows = runs_table(cfg)
                    return self._json(200, {"summary": summary(cfg, rows), "runs": rows})
                if path.startswith("/api/run/"):
                    r = run_detail(cfg, unquote(path[len("/api/run/"):]))
                    return self._json(200, r) if r else self._json(404, {"error": "no such dev run"})
                return self._json(404, {"error": "not found"})
            except json.JSONDecodeError:
                return self._json(503, {"error": "a run is being written right now; the page retries"})
            except Exception as e:  # noqa: BLE001  the page shows it and keeps its last data
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(cfg: dict, port: int = 8765):
    server = make_server(cfg, port)
    print(f"truthgate lab view: http://127.0.0.1:{port}  (dev runs from {cfg['data_dir']}; Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
