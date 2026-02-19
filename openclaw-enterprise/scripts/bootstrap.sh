#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
export PGPASSWORD="openclaw_dev"
psql -h 127.0.0.1 -U openclaw -d openclaw -f "$ROOT_DIR/sql/001_memory_schemas.sql"
psql -h 127.0.0.1 -U openclaw -d openclaw -f "$ROOT_DIR/sql/002_audit_ledger.sql"

printf "[4/4] Bootstrap completado.\n"
printf "Configura OPENCLAW_DB_URL y conecta tu runtime de OpenClaw al control-plane/openclaw.json\n"