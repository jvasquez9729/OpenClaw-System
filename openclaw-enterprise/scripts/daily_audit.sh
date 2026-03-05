#!/usr/bin/env bash
# =================================================================
# daily_audit.sh — Auditoría de seguridad diaria (Iniciativa 5.10)
# Ejecutar: crontab -e → 0 8 * * * /ruta/openclaw-enterprise/scripts/daily_audit.sh
# =================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$ROOT_DIR/logs/audit_$(date +%Y%m%d).log"
ALERT=0

mkdir -p "$ROOT_DIR/logs"

log()   { echo "[$(date +'%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
warn()  { echo "[WARN]  $*" | tee -a "$LOG_FILE"; ALERT=1; }
error() { echo "[ERROR] $*" | tee -a "$LOG_FILE"; ALERT=1; }
ok()    { echo "[ OK ]  $*" | tee -a "$LOG_FILE"; }

log "=== Auditoría diaria OpenClaw Enterprise ==="

# ── 1. PostgreSQL solo en localhost ─────────────────────────────
log "Verificando que PostgreSQL solo escucha en loopback..."
if command -v ss >/dev/null 2>&1; then
  EXPOSED=$(ss -tlnp 2>/dev/null | grep ':5432' | grep -v '127.0.0.1' || true)
else
  EXPOSED=$(netstat -tlnp 2>/dev/null | grep ':5432' | grep -v '127.0.0.1' || true)
fi
if [[ -n "$EXPOSED" ]]; then
  error "PostgreSQL expuesto fuera de localhost: $EXPOSED"
else
  ok "PostgreSQL solo en 127.0.0.1:5432"
fi

# ── 2. Docker container corriendo ──────────────────────────────
log "Verificando contenedor openclaw-postgres..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "openclaw-postgres"; then
  ok "Contenedor openclaw-postgres activo"
else
  warn "Contenedor openclaw-postgres NO está corriendo"
fi

# ── 3. .env no commiteado al repo ───────────────────────────────
log "Verificando que .env no está en git tracking..."
if git -C "$ROOT_DIR" ls-files --error-unmatch .env 2>/dev/null; then
  error ".env está trackeado por git — REMOVER INMEDIATAMENTE: git rm --cached .env"
else
  ok ".env no está en git"
fi

# ── 4. Sin credenciales hardcodeadas en scripts ─────────────────
log "Escaneando credenciales hardcodeadas en scripts..."
HARDCODED=$(grep -rn "openclaw_dev\|password.*=.*['\"][^$]" \
            "$ROOT_DIR/scripts/" "$ROOT_DIR/infra/" 2>/dev/null || true)
if [[ -n "$HARDCODED" ]]; then
  error "Posibles credenciales hardcodeadas encontradas:"
  echo "$HARDCODED" | tee -a "$LOG_FILE"
else
  ok "Sin credenciales hardcodeadas detectadas"
fi

# ── 5. Verificar hash chain del audit ledger ────────────────────
log "Verificando integridad del audit ledger..."
ENV_FILE="$ROOT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi
if [[ -n "${OPENCLAW_DB_URL:-}" ]]; then
  BROKEN=$(PGPASSWORD="${POSTGRES_PASSWORD:-}" \
    psql "$OPENCLAW_DB_URL" -tAc "
      SELECT count(*) FROM (
        SELECT event_id, event_hash,
               lag(event_hash) OVER (ORDER BY event_id) AS prev_hash,
               prev_event_hash
        FROM mem_audit.execution_ledger
      ) t
      WHERE prev_event_hash IS DISTINCT FROM prev_hash
        AND prev_event_hash IS NOT NULL
    " 2>/dev/null || echo "DB_UNAVAILABLE")
  if [[ "$BROKEN" == "0" ]]; then
    ok "Hash chain del ledger íntegro"
  elif [[ "$BROKEN" == "DB_UNAVAILABLE" ]]; then
    warn "No se pudo conectar a la DB para verificar el ledger"
  else
    error "Hash chain del ledger ROTO — $BROKEN eventos inconsistentes"
  fi
else
  warn "OPENCLAW_DB_URL no definida — no se verificó el ledger"
fi

# ── 6. Permisos del directorio de config ────────────────────────
log "Verificando permisos de openclaw.json..."
CONFIG="$ROOT_DIR/control-plane/openclaw.json"
if [[ "$(uname)" != "MINGW"* && "$(uname)" != "CYGWIN"* ]]; then
  PERM=$(stat -c "%a" "$CONFIG" 2>/dev/null || stat -f "%Lp" "$CONFIG" 2>/dev/null)
  if [[ "$PERM" == "600" || "$PERM" == "640" ]]; then
    ok "Permisos de openclaw.json correctos ($PERM)"
  else
    warn "Permisos de openclaw.json: $PERM — recomendado: 600"
  fi
fi

# ── Resumen ─────────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
if [[ $ALERT -eq 0 ]]; then
  log "=== Auditoría PASADA — sin alertas ==="
else
  log "=== Auditoría FALLIDA — revisar alertas arriba ==="
  exit 1
fi
