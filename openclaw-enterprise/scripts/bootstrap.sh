#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── C2: Cargar .env — nunca credenciales hardcodeadas aquí ──────
ENV_FILE="$ROOT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
  echo "[env] Variables cargadas desde .env"
else
  echo "[warn] No se encontró .env — usando variables del entorno actual."
  echo "       Copia .env.example → .env y configura tus credenciales."
fi

# Validar que las variables críticas estén definidas
for VAR in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  if [[ -z "${!VAR:-}" ]]; then
    echo "[error] Variable obligatoria no definida: $VAR"
    echo "        Copia .env.example → .env y rellena los valores."
    exit 1
  fi
done

printf "[1/4] Validando archivos clave...\n"
for f in \
  "$ROOT_DIR/control-plane/openclaw.json" \
  "$ROOT_DIR/policies/agent_capabilities.yaml" \
  "$ROOT_DIR/workflows/state_machine.yaml" \
  "$ROOT_DIR/sql/001_memory_schemas.sql" \
  "$ROOT_DIR/sql/002_audit_ledger.sql"; do
  [[ -f "$f" ]] || { echo "Falta $f"; exit 1; }
done

printf "[2/4] Levantando PostgreSQL (docker compose)...\n"
docker compose -f "$ROOT_DIR/infra/docker-compose.yml" up -d

printf "[3/4] Aplicando esquemas SQL...\n"
# PGPASSWORD desde variable de entorno — nunca hardcodeado
PGPASSWORD="$POSTGRES_PASSWORD" \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -f "$ROOT_DIR/sql/001_memory_schemas.sql"

PGPASSWORD="$POSTGRES_PASSWORD" \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       -f "$ROOT_DIR/sql/002_audit_ledger.sql"

printf "[4/4] Bootstrap completado.\n"
printf "Configura OPENCLAW_DB_URL y conecta tu runtime al control-plane/openclaw.json\n"
