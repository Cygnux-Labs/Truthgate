from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULTS = {
    "data_dir": "data",
    "work_dir": "work",
    "model": {
        "id": "Qwen/Qwen3.5-4B",
        "device": "auto",
        "dtype": "auto",
        "max_new_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.95,
        "layers": None,
        "chat_template_kwargs": {"enable_thinking": True},
    },
    "collect": {"samples_per_task": 3, "max_steps": 12, "templates": None, "faults": None, "pressures": None},
    "monitor": {"model": "claude-sonnet-5-5", "include_reasoning": True, "workers": 4},
    "claims": {"budget": 25},
}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def load_config(path: str | None = None) -> dict:
    path = path or os.environ.get("TRUTHGATE_CONFIG", "configs/mac.yaml")
    cfg = DEFAULTS
    if path and Path(path).exists():
        cfg = _merge(DEFAULTS, yaml.safe_load(Path(path).read_text()))
    return cfg


def make_backend(cfg: dict):
    from .backends import HFBackend
    m = cfg["model"]
    return HFBackend(m["id"], device=m["device"], dtype=m["dtype"], max_new_tokens=m["max_new_tokens"],
                     temperature=m["temperature"], top_p=m["top_p"], layers=m["layers"],
                     chat_template_kwargs=m["chat_template_kwargs"])
