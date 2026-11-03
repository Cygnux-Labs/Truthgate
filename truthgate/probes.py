"""Datasets of activations + labels, and simple probes.

All cross-validation is grouped by task template, so a probe is always scored on
tasks it never saw. AUROC is computed on pooled out-of-fold scores.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from .labels import CONTRASTS
from .steps import STEP_CONTRASTS, step_labels


def step_index(ep: dict, step: str | int) -> int | None:
    """'submit' = the agent step that produced the final claim; an int k = k steps before it."""
    s = ep.get("submit_step_index")
    if s is None:
        return None
    k = 0 if step == "submit" else int(step)
    return s - k if s - k >= 0 else None


def build(runs: list[dict], contrast: str, position: str = "pre", step: str | int = "submit"):
    """One sample per run, at `step`. For a step contrast (steps.STEP_CONTRASTS) see build_steps; `step` is unused."""
    if contrast in STEP_CONTRASTS:
        return build_steps(runs, contrast, position)
    pos, neg = CONTRASTS[contrast]
    X, y, groups, ids, labels = [], [], [], [], []
    for ep in runs:
        if ep["label"] not in pos | neg or "acts" not in ep:
            continue
        i = step_index(ep, step)
        if i is None:
            continue
        X.append(ep["acts"][position][i].astype(np.float32))
        y.append(1 if ep["label"] in pos else 0)
        groups.append(ep["task"]["template"])
        ids.append(ep["run_id"])
        labels.append(ep["label"])
    if not X:
        return None
    return {"X": np.stack(X), "y": np.array(y), "groups": np.array(groups), "ids": ids, "labels": labels,
            "contrast": contrast, "position": position, "step": step}


def build_steps(runs: list[dict], contrast: str, position: str = "pre"):
    """One sample per agent step, labelled from the host log (steps.step_labels). ids are "<run_id>@<step>".

    Groups are task templates, so grouped CV keeps every step of a run, and every run of a template,
    on one side of each split.
    lean: the claim checker bootstraps over samples, and here a sample is a step; steps of one run are
    correlated, so its CI is narrower than a run-level bootstrap would give. Upgrade: a bootstrap
    clustered by run in claims.py (locked; the owner's call).
    """
    pos, neg = STEP_CONTRASTS[contrast]
    X, y, groups, ids, labels = [], [], [], [], []
    for ep in runs:
        if "acts" not in ep:
            continue
        for i, lab in enumerate(step_labels(ep)):
            if lab not in pos | neg:
                continue
            X.append(ep["acts"][position][i].astype(np.float32))
            y.append(1 if lab in pos else 0)
            groups.append(ep["task"]["template"])
            ids.append(f"{ep['run_id']}@{i}")
            labels.append(lab)
    if not X:
        return None
    return {"X": np.stack(X), "y": np.array(y), "groups": np.array(groups), "ids": ids, "labels": labels,
            "contrast": contrast, "position": position, "step": "each"}


def _auc(y, s):
    return float(roc_auc_score(y, s)) if len(set(y)) == 2 else float("nan")


def fit_direction(X: np.ndarray, y: np.ndarray, method: str = "diffmeans", C: float = 0.05) -> np.ndarray:
    if method == "diffmeans":
        d = X[y == 1].mean(0) - X[y == 0].mean(0)
    elif method == "logreg":
        mu, sd = X.mean(0), X.std(0) + 1e-6
        clf = LogisticRegression(C=C, max_iter=2000).fit((X - mu) / sd, y)
        d = clf.coef_[0] / sd
    else:
        raise ValueError(method)
    return d / (np.linalg.norm(d) + 1e-12)


def oof_scores(X, y, groups, method="diffmeans", n_splits=5):
    n_groups = len(set(groups))
    k = max(2, min(n_splits, n_groups))
    scores = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        if len(set(y[tr])) < 2:
            continue
        d = fit_direction(X[tr], y[tr], method)
        scores[te] = X[te] @ d
    return scores


def layer_sweep(ds: dict, method: str = "diffmeans") -> list[dict]:
    X, y, g = ds["X"], ds["y"], ds["groups"]
    out = []
    for layer in range(X.shape[1]):
        s = oof_scores(X[:, layer], y, g, method)
        ok = ~np.isnan(s)
        out.append({"layer": layer, "auroc": _auc(y[ok], s[ok]), "n": int(ok.sum())})
    return out


def bootstrap_auc(y, s, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) == 2:
            vals.append(roc_auc_score(y[idx], s[idx]))
    if not vals:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def random_direction_null(X_layer, y, n=200, seed=0):
    """AUROC of random unit directions (fixed sign): the chance distribution for 'a direction'."""
    rng = np.random.default_rng(seed)
    D = rng.normal(size=(n, X_layer.shape[1]))
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    return np.array([_auc(y, X_layer @ d) for d in D])
