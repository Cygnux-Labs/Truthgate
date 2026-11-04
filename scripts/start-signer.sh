#!/bin/sh
# Start the referee's own Tracekit signer in the foreground (a person runs this, in a terminal of their own).
# It reads signer-data/signer.yaml, keeps its keys and store in signer-data/data, and listens on a loopback TCP port
# whose number and token it writes to signer-data/endpoint.json (0600). The harness reads that file at run time.
# Stop it with Ctrl-C.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
CFG="$ROOT/signer-data/signer.yaml"
if [ ! -f "$CFG" ]; then
  echo "no $CFG: save the signer config from the setup notes there first, then run this again" >&2
  exit 1
fi
mkdir -p "$ROOT/signer-data/data"
chmod 700 "$ROOT/signer-data/data"
# the trust config pins this signer's log key, so the harness can verify each bundle offline; written once the
# signer has made its key (first start), in the background while the signer runs
(
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if [ -f "$ROOT/signer-data/endpoint.json" ]; then
      "$PY" -I -m tracekit signer trust --config "$CFG" -o "$ROOT/signer-data/trust.json" >/dev/null && break
    fi
  done
) &
exec "$PY" -I -m tracekit signer serve --config "$CFG"
