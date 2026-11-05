# Dependencies and their risk

Each dependency: who maintains it, how widely it is used, and what it can reach in this project. Versions are pinned
in `requirements.txt`. Maintainers and licences are from the installed packages' metadata (`pip show`); adoption is a
judgment, not a measured download count.

| Package | Maintainer | Adoption | What it can reach here |
|---|---|---|---|
| `tracekit-ai` 1.5.3 | Cygnux Labs (this project's owner) | small, new | The harness process: the referee's own signer on loopback TCP with its token (read from `signer-data/endpoint.json`, kept in memory). `tracekit export` reads the signer's store under `signer-data/data`. Pulls `cryptography`, `google-re2`, `regex`, `rfc8785`. |
| `anthropic` 2.4.0 | Anthropic (official SDK, Apache-2.0) | very wide | The network, to the Anthropic API, with the key passed in memory (never in the environment, so no child process inherits it). Pulls `httpx2`, `pydantic`, `anyio`, `jiter`, `opentelemetry-api`. |
| `PyYAML` 6.0.3 | the PyYAML project (MIT) | very wide | Reads `rules.yaml` with `safe_load` only (no object construction). |
| `pyarrow` 26.0.1 | Apache Arrow, Apache Software Foundation | very wide | Reads the downloaded parquet files once, in `scripts/prepare_tasks.py`, run with `python -I`. A native library parsing untrusted files: the files are pinned by sha256 (`data/tasks/MANIFEST.json`). |
| `mlx-lm` 0.32.2, `mlx` 0.32.4 | Apple, ml-explore (MIT) | wide on Apple silicon | Loads a local model. Pulls `transformers` 5.22.1 and `huggingface_hub` 2.4.0 (Hugging Face, Apache-2.0), `tokenizers`, `safetensors`, `jinja2`, `sentencepiece`, `protobuf`, `numpy`. `huggingface_hub` downloads the model into `~/.cache/huggingface` (network). The model's weights are safetensors (no pickle); its chat template is Jinja from the model repo, rendered by transformers' sandboxed Jinja environment. The model is pinned by revision. Only the local backend imports it. |
| `pytest` 9.2.0 | pytest-dev (MIT) | very wide | Tests only. |

## Outside Python

| Item | Pin | Reach |
|---|---|---|
| Docker image `python:3.11-slim` | by digest in `sandbox/Dockerfile` | Runs the agent's commands and the hidden checks, with no network, a read-only root, no capabilities, uid 1000, CPU, memory and process limits. |
| `pytest` 8.3.3 inside the image | version pin, from PyPI at build time | Inside the sandbox only, so agents can run pytest and pytest-based tricks are possible to detect. |
| Model `mlx-community/Qwen3.5-4B-MLX-4bit` | revision `32f3e8ecf65426fc3306969496342d504bfa13f3` | Local inference only. |
| Dataset `fjzzq2002/impossible_livecodebench` | revision `98650ffc3f28a01b261669b6d19fcd7773823710`, file sha256s | Data only; never executed by the harness. Its tests run inside the sandbox. |
