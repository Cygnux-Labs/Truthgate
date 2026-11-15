#!/bin/sh
# The tamper pilot (docs/prereg-tamper-pilot.md) with its own signer, started for the commands given and stopped after:
#   sh scripts/tamper_pilot.sh run score      # the rollouts (paid: Sonnet 5.5), then the free scores and the gate
#   sh scripts/tamper_pilot.sh judge score    # the LLM judges (paid), then the scores again
# The signer (configured as v1's: signer-data/signer.yaml and policy.yaml) keeps its keys and store in
# runs/tamper-pilot/signer-data (git-ignored), made on the first run and kept: the pilot's evidence stays verifiable.
# Paid commands stop at the stage's $50 and spend through v1's Keychain key and spend ledger. Needs colima running.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/runs/tamper-pilot"
CFG="$OUT/signer-data/signer.yaml"

/opt/homebrew/bin/docker --context colima image inspect cygnux-referee-sandbox:0.1 >/dev/null 2>&1 || make image
if [ ! -f "$CFG" ]; then
  mkdir -p "$OUT/signer-data/data"
  chmod 700 "$OUT/signer-data/data"
  cp signer-data/signer.yaml signer-data/policy.yaml "$OUT/signer-data/"
fi
rm -f "$OUT/signer-data/endpoint.json"
"$PY" -I -m tracekit signer serve --config "$CFG" >>"$OUT/signer.log" 2>&1 &
SIGNER=$!
trap 'kill $SIGNER 2>/dev/null || true; wait $SIGNER 2>/dev/null || true' EXIT INT TERM
i=0
until [ -f "$OUT/signer-data/endpoint.json" ]; do
  i=$((i + 1))
  if [ $i -gt 60 ]; then echo "the signer did not start; see $OUT/signer.log" >&2; exit 1; fi
  sleep 1
done
"$PY" -I -m tracekit signer trust --config "$CFG" -o "$OUT/signer-data/trust.json" >/dev/null
for cmd in "$@"; do
  "$PY" -m referee.tamper_pilot "$cmd"
done
