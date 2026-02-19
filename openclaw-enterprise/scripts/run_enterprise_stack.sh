#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1) Bootstrap infra + SQL
bash "$ROOT_DIR/scripts/bootstrap.sh"

# 2) Export DB URL for current shell process
export OPENCLAW_DB_URL="postgresql://openclaw:openclaw_dev@127.0.0.1:5432/openclaw"

# 3) Validate config files
python -m json.tool "$ROOT_DIR/control-plane/openclaw.json" >/dev/null

echo "[ok] Bootstrap + config validation complete."
echo "OPENCLAW_DB_URL=$OPENCLAW_DB_URL"

# 4) Try to run OpenClaw runtime if installed
if command -v openclaw >/dev/null 2>&1; then
  echo "[run] openclaw detected, launching a sample run..."
  echo "[note] Adjust the command to your actual OpenClaw CLI syntax if needed."
  echo "openclaw run --config $ROOT_DIR/control-plane/openclaw.json --task 'Procesar estados financieros Q1'"
else
  echo "[warn] openclaw CLI not found in PATH."
  echo "Instala OpenClaw y luego ejecuta:"
  echo "openclaw run --config $ROOT_DIR/control-plane/openclaw.json --task 'Procesar estados financieros Q1'"
fi