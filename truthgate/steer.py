"""Causal test: add a direction to the residual stream and see if the final claim changes.

For each run we replay the exact conversation up to the moment the agent made its
final claim, then sample the final step again with and without steering.
Outcome per sample: "done", "not_done", or "other" (no submit call).

A direction found at hidden-state index i (0 = embeddings) is added to the output of
decoder layer i-1, at every position, scaled by alpha * (mean residual norm at that layer).
"""
from __future__ import annotations

import contextlib

import numpy as np

from .arena import TOOL_SPECS
from .backends import find_layers, parse_tool_call, split_reasoning


@contextlib.contextmanager
def add_direction(model, layer_index: int, vec):
    import torch
    if layer_index < 1:
        raise ValueError("cannot steer the embedding output (index 0); use index >= 1")
    layers = find_layers(model)
    v = torch.as_tensor(vec)

    def hook(_mod, _inp, out):
        if isinstance(out, tuple):
            h = out[0]
            return (h + v.to(h.device, h.dtype),) + tuple(out[1:])
        return out + v.to(out.device, out.dtype)

    handle = layers[layer_index - 1].register_forward_hook(hook, prepend=True)
    try:
        yield
    finally:
        handle.remove()


def mean_norm(runs, layer: int, position: str = "pre") -> float:
    norms = [np.linalg.norm(ep["acts"][position][:, layer].astype(np.float32), axis=-1).mean()
             for ep in runs if "acts" in ep]
    return float(np.mean(norms))


def sample_claims(backend, messages, n: int) -> list[str]:
    out = []
    for _ in range(n):
        prompt = backend.render(messages, TOOL_SPECS)
        enc = backend.tok(prompt, return_tensors="pt", add_special_tokens=False).to(backend.device)
        with backend.torch.no_grad():
            g = backend.model.generate(**enc, max_new_tokens=backend.max_new_tokens, do_sample=True,
                                       temperature=max(backend.temperature, 1e-5), top_p=backend.top_p,
                                       eos_token_id=backend.stop_ids, pad_token_id=backend.tok.pad_token_id or backend.tok.eos_token_id)
        raw = backend.tok.decode(g[0, enc["input_ids"].shape[1]:], skip_special_tokens=False)
        _, vis = split_reasoning(raw)
        tc = parse_tool_call(vis) or parse_tool_call(raw)
        if tc and tc["name"] == "submit":
            out.append("done" if str(tc["arguments"].get("status", "")).lower() == "done" else "not_done")
        else:
            out.append("other")
    return out


def steer_test(backend, runs, direction, layer: int, alphas=(0.0, -4.0, 4.0), n_samples: int = 4,
               norm_scale: float | None = None, seed: int = 0) -> dict:
    """Returns done-rate per alpha and the effect of each alpha vs alpha=0, with bootstrap CIs."""
    backend.torch.manual_seed(seed)
    usable = [ep for ep in runs if ep.get("submit_msg_index") is not None]
    scale = norm_scale if norm_scale is not None else mean_norm(usable, layer)
    d = np.asarray(direction, dtype=np.float32)
    d = d / np.linalg.norm(d)
    per_run = {a: [] for a in alphas}
    for ep in usable:
        msgs = ep["messages"][: ep["submit_msg_index"]]
        for a in alphas:
            if a == 0:
                outs = sample_claims(backend, msgs, n_samples)
            else:
                with add_direction(backend.model, layer, a * scale * d):
                    outs = sample_claims(backend, msgs, n_samples)
            per_run[a].append(np.mean([o == "done" for o in outs]))
    res = {"layer": layer, "norm_scale": scale, "n_runs": len(usable), "n_samples": n_samples, "alphas": {}}
    base = np.array(per_run[0.0]) if 0.0 in per_run else None
    rng = np.random.default_rng(seed)
    for a in alphas:
        r = np.array(per_run[a])
        entry = {"done_rate": float(r.mean()) if len(r) else float("nan")}
        if base is not None and a != 0 and len(r):
            diff = r - base
            boots = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(1000)]
            entry.update({"effect": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)),
                                                                 float(np.percentile(boots, 97.5))]})
        res["alphas"][str(a)] = entry
    return res
