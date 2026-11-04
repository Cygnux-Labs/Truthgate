# Run every target from this directory. The signer must be running for every real run (scripts/start-signer.sh).
PY := $(CURDIR)/.venv/bin/python
OUT ?= runs/pilot
MODELS ?= claude-sonnet-5-5,claude-haiku-5-5
N ?= 30
SEED ?= 20261104
MAX_USD ?= 40
WORKERS ?= 3
MLX_MODEL ?= mlx-community/Qwen3.5-4B-MLX-4bit

.PHONY: test image tasks pilot metrics recheck smoke-api smoke-mlx smoke-mlx-unsigned judge-dry judge-keyword judge-llm headtohead v1-cell v1-rescore v1-budget v1-calibrate v1-replay v1-judge v1-analyse timing

test:
	$(PY) -m pytest -q

image:
	/opt/homebrew/bin/docker --context colima build -t cygnux-referee-sandbox:0.1 sandbox

tasks:
	$(PY) -I scripts/prepare_tasks.py data/raw data/tasks

# 30 tasks x 3 variants x 2 API models; stops before the estimated spend passes MAX_USD
pilot:
	$(PY) -m referee.run --backend anthropic --models $(MODELS) --n $(N) --seed $(SEED) --max-usd $(MAX_USD) \
		--workers $(WORKERS) --out $(OUT)

metrics:
	$(PY) -m referee.metrics $(OUT)

recheck:
	$(PY) -m referee.recheck $(OUT)/*/

# two signed API rollouts (one impossible task each way), capped at $2
smoke-api:
	$(PY) -m referee.run --backend anthropic --models claude-haiku-5-5 --variants oneoff,conflicting --n 1 \
		--max-usd 2 --out runs/smoke-api

# three signed local-model rollouts, one per variant
smoke-mlx:
	$(PY) -m referee.run --backend mlx --models $(MLX_MODEL) --n 1 --out runs/smoke-mlx

# the same without a signer: checks the loop only; its verdicts say signed: false and the metrics leave them out
smoke-mlx-unsigned:
	$(PY) -m referee.run --backend mlx --models $(MLX_MODEL) --n 1 --unsigned-smoke --out runs/smoke-mlx-unsigned

# transcript-only judges and the head-to-head (docs/prereg-amendment-1.md); outputs in runs/judges/<run name>
JUDGE_USD ?= 10

judge-dry:
	$(PY) -m referee.judge $(OUT) --judge llm --dry-run

judge-keyword:
	$(PY) -m referee.judge $(OUT) --judge keyword

judge-llm:
	$(PY) -m referee.judge $(OUT) --judge llm --max-usd $(JUDGE_USD)

headtohead:
	$(PY) -m referee.headtohead $(OUT)

# study v1 (docs/prereg-v1.md). Each cell stops at the owner-approved boundary (runs/approved-usd.txt); run it again
# after the next $50 step and it resumes. Cells, in order: `make v1-budget`.
CONDITION ?= monitor-aware
MODEL ?= claude-haiku-5-5
VARIANTS ?= original,oneoff,conflicting
V1_N ?= 60
V1_WORKERS ?= 6

v1-cell:
	$(PY) -m referee.run --backend anthropic --rules rules-v1.yaml --condition $(CONDITION) --models $(MODEL) \
		--variants $(VARIANTS) --n $(V1_N) --seed $(SEED) --max-usd-to-boundary --workers $(V1_WORKERS) \
		--out runs/v1/$(CONDITION)

v1-rescore:
	$(PY) -m referee.rescore runs/pilot runs/v1/baseline --rules rules-v1.yaml

v1-budget:
	$(PY) -m referee.study budget runs/pilot

v1-calibrate:
	$(PY) -m referee.study calibrate runs/pilot

v1-replay:
	$(PY) -m referee.recheck --compare-rules rules-v1.yaml runs/pilot/*/

v1-judge:
	for c in baseline monitor-aware adversarial; do \
		$(PY) -m referee.judge runs/v1/$$c --judge keyword && \
		$(PY) -m referee.judge runs/v1/$$c --judge llm --max-usd $(JUDGE_USD) && \
		$(PY) -m referee.judge runs/v1/$$c --judge llm --max-usd $(JUDGE_USD) --tag r2 || exit 1; done

v1-analyse:
	$(PY) -m referee.study analyse --baseline runs/v1/baseline --monitor-aware runs/v1/monitor-aware \
		--adversarial runs/v1/adversarial

timing:
	$(PY) -m referee.timing $(OUT)
