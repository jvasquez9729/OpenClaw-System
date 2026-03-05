#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── C2: Cargar .env — nunca hardcodear credenciales en el script ─
ENV_FILE="$ROOT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
  echo "[env] Variables cargadas desde .env"
else
  echo "[warn] No se encontró .env — usando variables del entorno actual."
fi

# Validar variable crítica (construir desde partes si no está definida)
if [[ -z "${OPENCLAW_DB_URL:-}" ]]; then
  if [[ -n "${POSTGRES_USER:-}" && -n "${POSTGRES_PASSWORD:-}" && -n "${POSTGRES_DB:-}" ]]; then
    export OPENCLAW_DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
  else
    echo "[error] OPENCLAW_DB_URL no está definida. Revisa tu .env."
    exit 1
  fi
fi

# 1) Bootstrap infra + SQL
bash "$ROOT_DIR/scripts/bootstrap.sh"

# 2) Validar config JSON
python -m json.tool "$ROOT_DIR/control-plane/openclaw.json" >/dev/null

echo "[ok] Bootstrap + config validation complete."
# No imprimir la URL completa (contiene credenciales)
echo "[ok] OPENCLAW_DB_URL configurado."

# 3) Ejecutar runtime si está instalado
if command -v openclaw >/dev/null 2>&1; then
  echo "[run] openclaw detectado, iniciando..."
  openclaw run \
    --config "$ROOT_DIR/control-plane/openclaw.json" \
    --task "Procesar estados financieros Q1"
else
  echo "[warn] openclaw CLI no encontrado en PATH."
  echo "Instala OpenClaw y ejecuta:"
  echo "  openclaw run --config $ROOT_DIR/control-plane/openclaw.json --task 'Procesar estados financieros Q1'"
fi
