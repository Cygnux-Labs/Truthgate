#!/bin/sh
# The tamper demo from scratch (docs/results-v2-tamper-demo.md): a fresh Tracekit signer configured as v1's
# (signer-data/signer.yaml and policy.yaml, new keys and store), eight scripted rollouts through v1's sandbox and
# recorder, then every judge and the table. No model calls, no API spend. Needs Docker: colima by default
# (/opt/homebrew/bin/docker --context colima); REFEREE_DOCKER and REFEREE_DOCKER_CONTEXT pick another CLI or
# context. Everything it writes goes to runs/tamper-demo (git-ignored), which it deletes first.
# TRACEKIT_PY picks the Python, and so the Tracekit, that signs, verifies and analyses: by default the referee's venv
# (tracekit-ai 1.5.3, as v1); TRACEKIT_PY=/path/to/Tracekit/.venv/bin/python runs it all on that checkout instead.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PY="${TRACEKIT_PY:-$ROOT/.venv/bin/python}"
OUT="$ROOT/runs/tamper-demo"
CFG="$OUT/signer-data/signer.yaml"

"${REFEREE_DOCKER:-/opt/homebrew/bin/docker}" --context "${REFEREE_DOCKER_CONTEXT:-colima}" image inspect cygnux-referee-sandbox:0.1 >/dev/null 2>&1 || make image
rm -rf "$OUT"
mkdir -p "$OUT/signer-data/data"
chmod 700 "$OUT/signer-data/data"
cp signer-data/signer.yaml signer-data/policy.yaml "$OUT/signer-data/"

"$PY" -I -m tracekit signer serve --config "$CFG" >"$OUT/signer.log" 2>&1 &
SIGNER=$!
trap 'kill $SIGNER 2>/dev/null || true; wait $SIGNER 2>/dev/null || true' EXIT INT TERM
i=0
until [ -f "$OUT/signer-data/endpoint.json" ]; do
  i=$((i + 1))
  if [ $i -gt 60 ]; then echo "the signer did not start; see $OUT/signer.log" >&2; exit 1; fi
  sleep 1
done
"$PY" -I -m tracekit signer trust --config "$CFG" -o "$OUT/signer-data/trust.json" >/dev/null
echo "signer up: $("$PY" -I -m tracekit --version 2>/dev/null || echo tracekit), trust config $OUT/signer-data/trust.json"

"$PY" -m referee.tamper run --out "$OUT"
"$PY" -m referee.tamper score --out "$OUT"
