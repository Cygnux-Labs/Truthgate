# Run every target from this directory. The signer must be running for every real run (scripts/start-signer.sh).
PY := $(CURDIR)/.venv/bin/python
OUT ?= runs/pilot
MODELS ?= claude-sonnet-5-5,claude-haiku-5-5
N ?= 30
SEED ?= 20261104
MAX_USD ?= 40
WORKERS ?= 3
MLX_MODEL ?= mlx-community/Qwen3.5-4B-MLX-4bit

.PHONY: test image tasks pilot metrics recheck smoke-api smoke-mlx smoke-mlx-unsigned judge-dry judge-keyword judge-llm headtohead v1-cell v1-rescore v1-budget v1-calibrate v1-replay v1-judge v1-analyse timing spend approve-next synthetic-run synthetic-judge synthetic-report report-turns views-judge views-report v2-oneoff v2-original v2-drift v2-analyse v3-cell v3-d v3-d-original v3-probe v3-gate v3-c v3-analyse

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

RULES ?= rules.yaml

recheck:
	$(PY) -m referee.recheck --rules $(RULES) $(OUT)/[!_]*/

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
	$(PY) -m referee.recheck --compare-rules rules-v1.yaml runs/pilot/[!_]*/

# the judges on one v1 condition: keyword, then the LLM judge twice; each LLM pass stops at the approved boundary
v1-judge:
	$(PY) -m referee.judge runs/v1/$(CONDITION) --judge keyword
	$(PY) -m referee.judge runs/v1/$(CONDITION) --judge llm --max-usd-to-boundary
	$(PY) -m referee.judge runs/v1/$(CONDITION) --judge llm --max-usd-to-boundary --tag r2
	$(PY) -m referee.headtohead runs/v1/$(CONDITION)

spend:
	$(PY) -m referee.ledger show

approve-next:
	$(PY) -m referee.ledger approve-next

v1-analyse:
	$(PY) -m referee.study analyse --baseline runs/v1/baseline --monitor-aware runs/v1/monitor-aware

# the synthetic obfuscation suite (docs/prereg-v1.md, amendment 3): scripted agents, no model calls; then the judges
synthetic-run:
	$(PY) -m referee.synthetic run

synthetic-judge:
	$(PY) -m referee.judge runs/synthetic --judge keyword
	$(PY) -m referee.judge runs/synthetic --judge llm --dry-run
	$(PY) -m referee.judge runs/synthetic --judge llm --max-usd-to-boundary
	$(PY) -m referee.judge runs/synthetic --judge llm --max-usd-to-boundary --tag r2
	$(PY) -m referee.headtohead runs/synthetic

synthetic-report:
	$(PY) -m referee.synthetic report

timing:
	$(PY) -m referee.timing $(OUT)

# amendment 4b: the final-report turn (one API call per rollout, a signed event), then the judges on views v1, v2, v4
report-turns:
	$(PY) -m referee.report_turn $(OUT) --max-usd-to-boundary

views-judge:
	for v in v1 v2 v4; do \
		$(PY) -m referee.judge $(OUT) --view $$v --judge keyword && \
		$(PY) -m referee.judge $(OUT) --view $$v --judge llm --max-usd-to-boundary && \
		$(PY) -m referee.judge $(OUT) --view $$v --judge llm --max-usd-to-boundary --tag r2 || exit 1; done

views-report:
	$(PY) -m referee.views report

# study v2 (docs/prereg-v1.md, amendment 5): Sonnet, the same 60 oneoff and 30 original tasks, three one-sentence
# wordings; each command stops at the approved boundary and resumes when run again
V2_CONDITIONS ?= human-review recorded norm

v2-oneoff:
	for c in $(V2_CONDITIONS); do $(MAKE) v1-cell CONDITION=$$c MODEL=claude-sonnet-5-5 VARIANTS=oneoff V1_N=60 || exit 1; done

v2-original:
	for c in $(V2_CONDITIONS); do $(MAKE) v1-cell CONDITION=$$c MODEL=claude-sonnet-5-5 VARIANTS=original V1_N=30 || exit 1; done

v2-drift:
	$(PY) -m referee.run --backend anthropic --rules rules-v1.yaml --condition baseline --models claude-sonnet-5-5 \
		--variants oneoff --n 20 --seed $(SEED) --max-usd-to-boundary --workers $(V1_WORKERS) --out runs/v1/baseline-drift

v2-analyse:
	$(PY) -m referee.study v2

# study v3 (docs/prereg-v1.md, amendment 6). Each cell has its own --max-usd cap; cells run together have caps that sum
# to less than what is left of the approved total, so no ordering of their starts can pass it. Logs go to runs/logs/.
V3_WORKERS ?= 2
CAP ?= 35
D_MODEL := claude-sonnet-5-5
C_MODEL := claude-sonnet-5

v3-cell:
	$(PY) -m referee.run --backend anthropic --rules rules-v1.yaml --condition $(CONDITION) --models $(MODEL) \
		--variants $(VARIANTS) --n $(N3) --seed $(SEED) --max-usd $(CAP) --workers $(V3_WORKERS) \
		--out runs/v3/$(CONDITION)

# (d): the three arms together on Sonnet's oneoff tasks 1-60
v3-d:
	mkdir -p runs/logs
	$(MAKE) v3-cell CONDITION=recorded-private MODEL=$(D_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-d-recorded-private.log 2>&1 & \
	$(MAKE) v3-cell CONDITION=recorded MODEL=$(D_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-d-recorded.log 2>&1 & \
	$(MAKE) v3-cell CONDITION=baseline MODEL=$(D_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-d-baseline.log 2>&1 & \
	wait

v3-d-original:
	mkdir -p runs/logs
	$(MAKE) v3-cell CONDITION=recorded-private MODEL=$(D_MODEL) VARIANTS=original N3=30 CAP=$(CAP) \
		> runs/logs/v3-d-original.log 2>&1

# (c): the probe (the second model's baseline on oneoff tasks 1-20), its gate, then its cells together if it passes
v3-probe:
	mkdir -p runs/logs
	$(MAKE) v3-cell CONDITION=baseline MODEL=$(C_MODEL) VARIANTS=oneoff N3=20 CAP=$(CAP) > runs/logs/v3-c-probe.log 2>&1

v3-gate:
	$(PY) -m referee.study gate

v3-c: v3-gate
	mkdir -p runs/logs
	$(MAKE) v3-cell CONDITION=baseline MODEL=$(C_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-c-baseline.log 2>&1 & \
	$(MAKE) v3-cell CONDITION=recorded MODEL=$(C_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-c-recorded.log 2>&1 & \
	$(MAKE) v3-cell CONDITION=norm MODEL=$(C_MODEL) VARIANTS=oneoff N3=60 CAP=$(CAP) \
		> runs/logs/v3-c-norm.log 2>&1 & \
	wait

v3-analyse:
	$(PY) -m referee.study v3
