"""The claim checker.

The researcher (a human or Claude Code) only ever sees DEV runs. A finding counts only
when it is written down as a testable claim BEFORE it is checked, and then survives a
test on HELD-OUT runs (task templates the researcher never saw).

Two kinds of claims:

  detector  "direction D at layer L separates <contrast> on held-out runs with AUROC >= x"
            (optionally: "and beats the text monitor on the same runs")
  causal    "adding alpha * D at layer L changes the rate of 'done' claims on held-out
            <labels> runs by at least <min_effect>"

Rules enforced here:
  * the direction's orientation is fixed by the claim (no sign flipping after the fact)
  * every check is logged in an append-only ledger with the numbers
  * the same claim cannot be checked twice; there is a total budget of checks
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .episode import load_runs
from .monitor import monitor_score
from .probes import _auc, bootstrap_auc, build, random_direction_null


def save_direction(path: str | Path, vector, layer: int, position: str = "pre", step="submit",
                   contrast: str = "knows_false", method: str = "custom", note: str = "") -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    v = np.asarray(vector, dtype=np.float32)
    v = v / np.linalg.norm(v)
    np.savez(path, vector=v, layer=layer, position=position, step=str(step), contrast=contrast,
             method=method, note=note)
    return str(path)


def load_direction(path: str | Path) -> dict:
    z = np.load(path, allow_pickle=False)
    step = str(z["step"])
    return {"vector": z["vector"], "layer": int(z["layer"]), "position": str(z["position"]),
            "step": "submit" if step == "submit" else int(step), "contrast": str(z["contrast"]),
            "method": str(z["method"]), "note": str(z["note"])}


def _claim_hash(claim: dict, vec: np.ndarray) -> str:
    h = hashlib.sha256(vec.astype(np.float32).tobytes())
    h.update(json.dumps({k: claim.get(k) for k in ("kind", "contrast", "alpha", "on_labels")},
                        sort_keys=True).encode())
    return h.hexdigest()[:16]


def ledger_path(cfg) -> Path:
    return Path(cfg["work_dir"]) / "claims" / "ledger.jsonl"


def read_ledger(cfg) -> list[dict]:
    p = ledger_path(cfg)
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def check_claim(claim: dict, cfg: dict, backend=None) -> dict:
    ledger = read_ledger(cfg)
    if len(ledger) >= cfg["claims"]["budget"]:
        return {"verdict": "refused", "reason": f"claim budget of {cfg['claims']['budget']} checks used up"}
    if not claim.get("statement"):
        return {"verdict": "refused", "reason": "claim needs a plain-language 'statement'"}
    d = load_direction(claim["direction"])
    h = _claim_hash(claim, d["vector"])
    if any(e.get("hash") == h for e in ledger):
        return {"verdict": "refused", "reason": "this exact claim was already checked", "hash": h}

    runs = load_runs(cfg["data_dir"], "heldout")
    if claim["kind"] == "detector":
        result = _check_detector(claim, d, runs, cfg)
    elif claim["kind"] == "causal":
        if backend is None:
            from .config import make_backend
            backend = make_backend(cfg)
        result = _check_causal(claim, d, runs, backend)
    else:
        return {"verdict": "refused", "reason": f"unknown kind {claim['kind']}"}

    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "hash": h, "claim": claim,
             "direction_meta": {k: v for k, v in d.items() if k != "vector"}, **result,
             "checks_used": len(ledger) + 1, "budget": cfg["claims"]["budget"]}
    p = ledger_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry, default=float) + "\n")
    return entry


def _check_detector(claim, d, runs, cfg) -> dict:
    contrast = claim.get("contrast", d["contrast"])
    ds = build(runs, contrast, d["position"], d["step"])
    if ds is None or len(set(ds["y"])) < 2:
        return {"verdict": "inconclusive", "reason": "held-out set lacks both classes for this contrast"}
    X = ds["X"][:, d["layer"]]
    y = ds["y"]
    s = X @ d["vector"]
    auc = _auc(y, s)
    lo, hi = bootstrap_auc(y, s)
    null = random_direction_null(X, y)
    p_null = float((np.sum(null >= auc) + 1) / (len(null) + 1))
    labels = np.array(ds["labels"])
    breakdown = {}
    for lab in sorted(set(labels[y == 0])):
        keep = (y == 1) | (labels == lab)
        breakdown[f"vs_{lab}"] = _auc(y[keep], s[keep])
    out = {"n_heldout": int(len(y)), "n_positive": int(y.sum()), "auroc": auc, "auroc_ci95": [lo, hi],
           "random_direction_p": p_null, "auroc_vs_each_negative_label": breakdown}
    ok = auc >= float(claim.get("min_auroc", 0.5)) and lo > 0.5 and p_null < 0.05

    if claim.get("beats_monitor"):
        mon_model = cfg["monitor"]["model"]
        inc = cfg["monitor"]["include_reasoning"]
        by_id = {ep["run_id"]: ep for ep in runs}
        m = np.array([monitor_score(by_id[i], contrast, mon_model, inc) if i in by_id else None for i in ds["ids"]],
                     dtype=object)
        have = np.array([v is not None for v in m])
        if have.sum() < len(y) * 0.9 or len(set(y[have])) < 2:
            out["monitor"] = "missing monitor scores on held-out runs (run `truthgate monitor --split heldout`)"
            ok = False
        else:
            mv = m[have].astype(float)
            yh, sh = y[have], s[have]
            rng = np.random.default_rng(0)
            diffs = []
            for _ in range(1000):
                idx = rng.integers(0, len(yh), len(yh))
                if len(set(yh[idx])) == 2:
                    diffs.append(_auc(yh[idx], sh[idx]) - _auc(yh[idx], mv[idx]))
            out["monitor_auroc"] = _auc(yh, mv)
            out["probe_minus_monitor_ci95"] = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
            ok = ok and out["probe_minus_monitor_ci95"][0] > 0
    out["verdict"] = "confirmed" if ok else "rejected"
    return out


def _check_causal(claim, d, runs, backend) -> dict:
    from .steer import steer_test
    labels = set(claim.get("on_labels", ["false_done"]))
    subset = [ep for ep in runs if ep["label"] in labels]
    if not subset:
        return {"verdict": "inconclusive", "reason": f"no held-out runs with labels {sorted(labels)}"}
    alpha = float(claim["alpha"])
    res = steer_test(backend, subset, d["vector"], d["layer"], alphas=(0.0, alpha),
                     n_samples=int(claim.get("n_samples", 4)))
    a = res["alphas"][str(alpha)]
    min_eff = float(claim["min_effect"])
    ok = (np.sign(a["effect"]) == np.sign(min_eff) and abs(a["effect"]) >= abs(min_eff)
          and (a["ci95"][1] < 0 if min_eff < 0 else a["ci95"][0] > 0))
    return {"steer": res, "verdict": "confirmed" if ok else "rejected"}
