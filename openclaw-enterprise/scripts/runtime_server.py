from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency fallback
    psycopg = None  # type: ignore[assignment]

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None


logger = logging.getLogger("openclaw.runtime.bridge")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

APP_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_ROOT / "control-plane" / "openclaw.json"
AGENT_CAPABILITIES_PATH = APP_ROOT / "policies" / "agent_capabilities.yaml"
PROMPTS_DIR = APP_ROOT / "prompts"

DEFAULT_AGENT_IDS = (
    "chief_of_staff",
    "financial_analyst",
    "financial_parser",
    "developer",
    "code_reviewer",
    "security_agent",
)
TERMINAL_STATUSES = {"DONE", "APPROVED", "REJECTED", "FAILED", "ERROR", "COMPLETED"}
CHAT_CONTEXT_LIMIT = int(os.getenv("CHAT_CONTEXT_LIMIT", "20"))

SOURCE_UI = "ui"
SOURCE_TELEGRAM = "telegram"
SOURCE_PROXY = "proxy"
VALID_SOURCES = {SOURCE_UI, SOURCE_TELEGRAM, SOURCE_PROXY}

OPENCLAW_ENDPOINT_CANDIDATES: dict[str, list[str]] = {
    "chat_post": ["/runtime/chat", "/api/runtime/chat", "/chat"],
    "chat_history": ["/runtime/chat/history/{agent_id}", "/api/runtime/chat/history/{agent_id}"],
    "chat_agents": ["/runtime/chat/agents", "/api/runtime/chat/agents"],
    "permission_stats": ["/runtime/permission/stats", "/api/runtime/permission/stats"],
    "permission_recent": ["/runtime/permission/recent", "/api/runtime/permission/recent"],
    "agents_state": ["/runtime/agents/state", "/api/runtime/agents/state"],
    "executions": ["/runtime/executions", "/api/runtime/executions"],
    "status": ["/runtime/status/{execution_id}", "/api/runtime/status/{execution_id}"],
    "approve": ["/runtime/approve", "/api/runtime/approve"],
    "reject": ["/runtime/reject", "/api/runtime/reject"],
}

_OPENAPI_CACHE: dict[str, Any] = {"fetched_at": 0.0, "paths": set()}
_CACHE_TTL_SECONDS = 20.0


class ChatRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source: str = Field(default=SOURCE_UI)
    execution_id: str | None = None


class ApprovalRequest(BaseModel):
    execution_id: str = Field(min_length=1)
    approved: bool | None = True
    reason: str | None = None
    source: str = Field(default=SOURCE_UI)


class RuntimeEventIngest(BaseModel):
    event_type: str = Field(min_length=1)
    agent_id: str | None = None
    execution_id: str | None = None
    status: str | None = None
    source: str = Field(default="webhook")
    payload: dict[str, Any] | None = None
    created_at: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _normalize_status(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if not s:
        return "PROPOSED"
    if "HITL" in s or "WAIT" in s:
        return "HITL_WAIT"
    if "RUN" in s or s == "IN_PROGRESS":
        return "RUNNING"
    if "APPROV" in s:
        return "APPROVED"
    if "REJECT" in s:
        return "REJECTED"
    if "DONE" in s or "COMPLETE" in s or "SUCCESS" in s:
        return "DONE"
    if "FAIL" in s or "ERROR" in s:
        return "FAILED"
    return s


def _first_non_empty(row: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _load_json_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo cargar openclaw.json: %s", exc)
        return {}


CONFIG = _load_json_config()


def _get_setting(env_key: str, config_key: str, default: str) -> str:
    env_value = os.getenv(env_key)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    config_value = CONFIG.get(config_key)
    if isinstance(config_value, str) and config_value.strip():
        return config_value.strip()
    return default


def _openclaw_base_url() -> str:
    return _get_setting("OPENCLAW_BASE_URL", "openclaw_base_url", "http://127.0.0.1:8000").rstrip("/")


def _openclaw_base_candidates() -> list[str]:
    env_list = os.getenv("OPENCLAW_BASE_URLS", "").strip()
    if env_list:
        parsed = [x.strip().rstrip("/") for x in env_list.split(",") if x.strip()]
    else:
        parsed = []

    cfg_list: list[str] = []
    raw_cfg = CONFIG.get("openclaw_base_urls")
    if isinstance(raw_cfg, list):
        cfg_list = [str(x).strip().rstrip("/") for x in raw_cfg if str(x).strip()]

    # Orden: variable dedicada -> config list -> base individual -> defaults conocidos.
    ordered = parsed + cfg_list + [_openclaw_base_url(), "http://127.0.0.1:3000", "http://127.0.0.1:8000"]
    unique: list[str] = []
    seen: set[str] = set()
    for item in ordered:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _ollama_base_url() -> str:
    return _get_setting("OLLAMA_BASE_URL", "ollama_base_url", "http://127.0.0.1:11434").rstrip("/")


def _default_ollama_model() -> str:
    return _get_setting("OLLAMA_MODEL", "ollama_model", "llama3.2")


def _require_psycopg() -> None:
    if psycopg is None:
        raise RuntimeError(
            "Falta dependencia psycopg para PostgreSQL. "
            "Instala psycopg y reintenta."
        )


def _db_connect():
    _require_psycopg()
    return psycopg.connect(  # type: ignore[union-attr]
        host=_get_setting("PGHOST", "pg_host", "127.0.0.1"),
        port=int(_get_setting("PGPORT", "pg_port", "5433")),
        user=_get_setting("PGUSER", "pg_user", "aiadmin"),
        password=os.getenv("PGPASSWORD", CONFIG.get("pg_password", "")),
        dbname=_get_setting("PGDATABASE", "pg_database", "openclaw"),
        autocommit=False,
    )


def ensure_tables() -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS mem_audit;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.chat_messages (
                  id BIGSERIAL PRIMARY KEY,
                  agent_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  source TEXT NOT NULL DEFAULT 'ui',
                  execution_id TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_events (
                  id BIGSERIAL PRIMARY KEY,
                  event_type TEXT NOT NULL,
                  agent_id TEXT,
                  execution_id TEXT,
                  status TEXT,
                  source TEXT NOT NULL DEFAULT 'runtime',
                  payload JSONB,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_executions (
                  execution_id TEXT PRIMARY KEY,
                  agent_id TEXT,
                  title TEXT,
                  description TEXT,
                  status TEXT NOT NULL DEFAULT 'PROPOSED',
                  cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                  source TEXT NOT NULL DEFAULT 'runtime',
                  payload JSONB,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_agent_created_at
                ON mem_audit.chat_messages(agent_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_events_created_at
                ON mem_audit.runtime_events(created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_exec_updated_at
                ON mem_audit.runtime_executions(updated_at DESC);
                """
            )
        conn.commit()


def _table_exists(schema: str, table: str) -> bool:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f"{schema}.{table}",))
            row = cur.fetchone()
    return bool(row and row[0])


def fetch_execution_ledger_rows(limit: int, execution_id: str | None = None) -> list[dict[str, Any]]:
    if not _table_exists("mem_audit", "execution_ledger"):
        return []

    with _db_connect() as conn:
        with conn.cursor() as cur:
            if execution_id:
                cur.execute(
                    """
                    SELECT to_jsonb(t) AS row
                    FROM mem_audit.execution_ledger t
                    WHERE execution_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (execution_id, max(1, limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT to_jsonb(t) AS row
                    FROM mem_audit.execution_ledger t
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (max(1, limit),),
                )
            rows = cur.fetchall()
    return [row[0] for row in rows if row and isinstance(row[0], dict)]


def map_ledger_row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    ts = _coerce_datetime(_first_non_empty(row, ("updated_at", "created_at", "timestamp")))
    status = _normalize_status(_first_non_empty(row, ("status", "state", "decision", "result"), "PROPOSED"))
    reason = _first_non_empty(
        row,
        ("reason", "description", "message", "summary", "action", "decision_reason", "task", "title"),
        "",
    )
    return {
        "timestamp": _to_iso(ts),
        "agent_id": str(_first_non_empty(row, ("agent_id", "agent", "owner"), "system")),
        "execution_id": _first_non_empty(row, ("execution_id", "run_id", "id")),
        "status": status,
        "reason": str(reason or status),
        "source": str(_first_non_empty(row, ("source",), "openclaw")),
    }


def map_ledger_rows_to_executions(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        execution_id = str(_first_non_empty(row, ("execution_id", "run_id", "id"), "") or "").strip()
        if not execution_id:
            continue
        if execution_id in seen:
            continue
        seen.add(execution_id)
        ts = _coerce_datetime(_first_non_empty(row, ("updated_at", "created_at", "timestamp")))
        status = _normalize_status(_first_non_empty(row, ("status", "state", "decision", "result"), "PROPOSED"))
        title = _first_non_empty(row, ("title", "task", "name"), f"Execution {execution_id}")
        description = _first_non_empty(
            row,
            ("description", "reason", "message", "summary", "decision_reason", "action"),
            "",
        )
        items.append(
            {
                "execution_id": execution_id,
                "agent_id": _first_non_empty(row, ("agent_id", "agent", "owner"), "chief_of_staff"),
                "title": str(title),
                "description": str(description),
                "status": status,
                "state": status,
                "updated_at": _to_iso(ts),
                "created_at": _to_iso(_coerce_datetime(_first_non_empty(row, ("created_at", "timestamp")))),
                "cost_usd": float(_first_non_empty(row, ("cost_usd",), 0) or 0),
            }
        )
        if len(items) >= limit:
            break
    return items


def _extract_agent_mapping(raw_data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_data, dict):
        return {}

    root: Any = raw_data
    for key in ("agents", "agent_capabilities", "capabilities"):
        if isinstance(raw_data.get(key), dict):
            root = raw_data[key]
            break

    out: dict[str, dict[str, Any]] = {}
    if isinstance(root, dict):
        for agent_id, cfg in root.items():
            if isinstance(agent_id, str):
                out[agent_id] = cfg if isinstance(cfg, dict) else {}
    return out


def _fallback_parse_capabilities(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, dict[str, Any]] = {}
    current_agent: str | None = None
    in_agents_block = False

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        top_match = re.match(r"^([a-zA-Z0-9_\-]+):\s*$", line)
        if top_match and line == line.lstrip():
            key = top_match.group(1)
            if key in {"agents", "agent_capabilities", "capabilities"}:
                in_agents_block = True
                current_agent = None
                continue
            if not in_agents_block:
                current_agent = key
                out.setdefault(current_agent, {})
                continue

        nested_agent = re.match(r"^\s{2}([a-zA-Z0-9_\-]+):\s*$", line)
        if in_agents_block and nested_agent:
            current_agent = nested_agent.group(1)
            out.setdefault(current_agent, {})
            continue

        if current_agent:
            kv = re.match(r"^\s{2,}([a-zA-Z0-9_\-]+):\s*(.+?)\s*$", line)
            if kv:
                k, v = kv.groups()
                out[current_agent][k] = v.strip("'\"")
    return out


def load_agent_capabilities() -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    if AGENT_CAPABILITIES_PATH.exists():
        if yaml is not None:
            try:
                with AGENT_CAPABILITIES_PATH.open("r", encoding="utf-8") as f:
                    parsed = _extract_agent_mapping(yaml.safe_load(f) or {})
            except Exception as exc:
                logger.warning("No se pudo parsear agent_capabilities.yaml con PyYAML: %s", exc)
        if not parsed:
            parsed = _fallback_parse_capabilities(AGENT_CAPABILITIES_PATH)
    for agent_id in DEFAULT_AGENT_IDS:
        parsed.setdefault(agent_id, {})
    return parsed


def _resolve_agent_model(agent_cfg: dict[str, Any]) -> str:
    for key in ("model", "ollama_model", "llm_model", "default_model"):
        value = agent_cfg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _default_ollama_model()


def _resolve_prompt(agent_id: str, agent_cfg: dict[str, Any]) -> str:
    for key in ("system_prompt", "prompt", "instructions"):
        value = agent_cfg.get(key)
        if isinstance(value, str) and value.strip():
            trimmed = value.strip()
            if "\n" in trimmed:
                return trimmed
            path = (APP_ROOT / trimmed).resolve() if not Path(trimmed).is_absolute() else Path(trimmed)
            if path.exists():
                return path.read_text(encoding="utf-8")

    for key in ("prompt_file", "system_prompt_file", "prompt_path"):
        value = agent_cfg.get(key)
        if isinstance(value, str) and value.strip():
            path = (APP_ROOT / value.strip()).resolve() if not Path(value).is_absolute() else Path(value)
            if path.exists():
                return path.read_text(encoding="utf-8")

    for candidate in (PROMPTS_DIR / f"{agent_id}.md", PROMPTS_DIR / f"{agent_id.replace('_', '-')}.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    return f"You are OpenClaw agent '{agent_id}'. Follow instructions safely and concisely."


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, method=method.upper(), headers=headers)
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def _refresh_openapi_cache() -> None:
    now = _utc_now().timestamp()
    fetched_at = float(_OPENAPI_CACHE.get("fetched_at") or 0.0)
    if (now - fetched_at) < _CACHE_TTL_SECONDS:
        return

    chosen_base = None
    chosen_paths: set[str] = set()
    for base_url in _openclaw_base_candidates():
        try:
            payload = _http_json(method="GET", url=f"{base_url}/openapi.json", timeout=5)
            if not isinstance(payload, dict):
                continue
            paths = set((payload.get("paths") or {}).keys())
            if not paths:
                continue
            chosen_base = base_url
            chosen_paths = paths
            break
        except Exception:
            continue

    _OPENAPI_CACHE["base_url"] = chosen_base
    _OPENAPI_CACHE["paths"] = chosen_paths
    _OPENAPI_CACHE["fetched_at"] = now


def _proxy_openclaw(
    *,
    key: str,
    method: str,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any | None:
    _refresh_openapi_cache()
    discovered = _OPENAPI_CACHE.get("paths") or set()
    candidates = OPENCLAW_ENDPOINT_CANDIDATES.get(key, [])
    ordered_paths: list[str] = []

    for discovered_path in discovered:
        if discovered_path in candidates:
            ordered_paths.append(discovered_path)
    ordered_paths.extend(candidates)

    seen: set[str] = set()
    base_urls = []
    cached_base = _OPENAPI_CACHE.get("base_url")
    if isinstance(cached_base, str) and cached_base.strip():
        base_urls.append(cached_base.strip().rstrip("/"))
    for candidate in _openclaw_base_candidates():
        if candidate not in base_urls:
            base_urls.append(candidate)

    for base_url in base_urls:
        for path in ordered_paths:
            cache_key = f"{base_url}:{path}"
            if cache_key in seen:
                continue
            seen.add(cache_key)

            final_path = path
            for name, value in (path_params or {}).items():
                final_path = final_path.replace(f"{{{name}}}", urllib_parse.quote(str(value)))
            query = urllib_parse.urlencode({k: v for k, v in (query_params or {}).items() if v is not None})
            url = f"{base_url}{final_path}"
            if query:
                url = f"{url}?{query}"

            try:
                return _http_json(method=method, url=url, payload=payload, timeout=20)
            except urllib_error.HTTPError as exc:
                if exc.code in (404, 405):
                    continue
                logger.warning("Proxy OpenClaw fallo %s %s: HTTP %s", method, url, exc.code)
                continue
            except Exception:
                continue
    return None


def insert_chat_message(
    *,
    agent_id: str,
    role: str,
    content: str,
    source: str,
    execution_id: str | None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    created = created_at or _utc_now()
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.chat_messages (agent_id, role, content, source, execution_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (agent_id, role, content, source, execution_id, created),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "id": row[0],
        "agent_id": agent_id,
        "role": role,
        "content": content,
        "source": source,
        "execution_id": execution_id,
        "created_at": _to_iso(row[1]),
    }


def fetch_chat_history_local(agent_id: str, limit: int) -> list[dict[str, Any]]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, agent_id, role, content, source, execution_id, created_at
                FROM mem_audit.chat_messages
                WHERE agent_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (agent_id, limit),
            )
            rows = cur.fetchall()
    rows.reverse()
    return [
        {
            "id": row[0],
            "agent_id": row[1],
            "role": row[2],
            "content": row[3],
            "source": row[4],
            "execution_id": row[5],
            "created_at": _to_iso(row[6]),
        }
        for row in rows
    ]


def insert_runtime_event(
    *,
    event_type: str,
    agent_id: str | None,
    execution_id: str | None,
    status: str | None,
    source: str,
    payload: dict[str, Any] | None,
    created_at: datetime | None = None,
) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_events (
                  event_type, agent_id, execution_id, status, source, payload, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    event_type,
                    agent_id,
                    execution_id,
                    status,
                    source,
                    json.dumps(payload or {}),
                    created_at or _utc_now(),
                ),
            )
        conn.commit()


def upsert_runtime_execution(
    *,
    execution_id: str,
    agent_id: str | None,
    title: str | None,
    description: str | None,
    status: str,
    source: str,
    cost_usd: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_executions (
                  execution_id, agent_id, title, description, status, source, cost_usd, payload, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
                ON CONFLICT (execution_id) DO UPDATE SET
                  agent_id = EXCLUDED.agent_id,
                  title = COALESCE(EXCLUDED.title, mem_audit.runtime_executions.title),
                  description = COALESCE(EXCLUDED.description, mem_audit.runtime_executions.description),
                  status = EXCLUDED.status,
                  source = EXCLUDED.source,
                  cost_usd = EXCLUDED.cost_usd,
                  payload = EXCLUDED.payload,
                  updated_at = now()
                """,
                (
                    execution_id,
                    agent_id,
                    title,
                    description,
                    status,
                    source,
                    float(cost_usd or 0),
                    json.dumps(payload or {}),
                ),
            )
        conn.commit()


def fetch_executions_local(limit: int) -> list[dict[str, Any]]:
    ledger_rows = fetch_execution_ledger_rows(limit=max(200, limit * 5))
    if ledger_rows:
        return map_ledger_rows_to_executions(ledger_rows, limit)

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT execution_id, agent_id, title, description, status, updated_at, created_at, cost_usd
                FROM mem_audit.runtime_executions
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            "execution_id": row[0],
            "agent_id": row[1],
            "title": row[2],
            "description": row[3],
            "status": _normalize_status(row[4]),
            "state": _normalize_status(row[4]),
            "updated_at": _to_iso(row[5]),
            "created_at": _to_iso(row[6]),
            "cost_usd": float(row[7] or 0),
        }
        for row in rows
    ]


def fetch_execution_local(execution_id: str) -> dict[str, Any] | None:
    ledger_rows = fetch_execution_ledger_rows(limit=200, execution_id=execution_id)
    if ledger_rows:
        mapped = map_ledger_rows_to_executions(ledger_rows, limit=1)
        if mapped:
            return mapped[0]

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT execution_id, agent_id, title, description, status, updated_at, created_at, cost_usd
                FROM mem_audit.runtime_executions
                WHERE execution_id = %s
                """,
                (execution_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "execution_id": row[0],
        "agent_id": row[1],
        "title": row[2],
        "description": row[3],
        "status": _normalize_status(row[4]),
        "state": _normalize_status(row[4]),
        "updated_at": _to_iso(row[5]),
        "created_at": _to_iso(row[6]),
        "cost_usd": float(row[7] or 0),
    }


def fetch_recent_events_local(limit: int) -> list[dict[str, Any]]:
    ledger_rows = fetch_execution_ledger_rows(limit=limit)
    if ledger_rows:
        items = [map_ledger_row_to_event(row) for row in reversed(ledger_rows)]
        return items

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, agent_id, execution_id, status, source, payload, created_at
                FROM mem_audit.runtime_events
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    rows.reverse()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = row[5] if isinstance(row[5], dict) else {}
        items.append(
            {
                "timestamp": _to_iso(row[6]),
                "agent_id": row[1] or payload.get("agent_id") or "system",
                "status": _normalize_status(row[3] or row[0]),
                "reason": payload.get("content") or payload.get("message") or row[0],
                "source": row[4],
                "execution_id": row[2],
            }
        )
    return items


def compute_permission_stats_local() -> dict[str, Any]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if _table_exists("mem_audit", "execution_ledger"):
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM mem_audit.execution_ledger
                    WHERE created_at >= now() - interval '24 hours'
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM mem_audit.runtime_events
                    WHERE created_at >= now() - interval '24 hours'
                    """
                )
            row = cur.fetchone()
    return {"active_tokens": int(row[0] if row else 0)}


def compute_agents_state_local() -> list[dict[str, Any]]:
    capabilities = load_agent_capabilities()
    status_by_agent: dict[str, str] = {}
    all_agent_ids = set(capabilities.keys()) | set(DEFAULT_AGENT_IDS)

    ledger_rows = fetch_execution_ledger_rows(limit=1000)
    if ledger_rows:
        for row in ledger_rows:
            agent_id = str(_first_non_empty(row, ("agent_id", "agent", "owner"), "") or "").strip()
            if not agent_id:
                continue
            if agent_id in status_by_agent:
                continue
            status_by_agent[agent_id] = _normalize_status(_first_non_empty(row, ("status", "state", "decision"), "IDLE"))
            all_agent_ids.add(agent_id)
    else:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (agent_id) agent_id, status, updated_at
                    FROM mem_audit.runtime_executions
                    WHERE agent_id IS NOT NULL
                    ORDER BY agent_id, updated_at DESC
                    """
                )
                rows = cur.fetchall()
                cur.execute("SELECT DISTINCT agent_id FROM mem_audit.chat_messages")
                chat_agents = [r[0] for r in cur.fetchall()]
        status_by_agent = {str(row[0]): _normalize_status(row[1]) for row in rows if row[0]}
        all_agent_ids |= set(chat_agents) | set(status_by_agent.keys())

    items: list[dict[str, Any]] = []
    for agent_id in sorted(all_agent_ids):
        status = status_by_agent.get(agent_id, "IDLE")
        if status == "RUNNING":
            state = "working"
        elif status == "HITL_WAIT":
            state = "hitl_wait"
        else:
            state = "idle"
        items.append(
            {
                "agent_id": agent_id,
                "state": state,
                "status": status,
                "cost_usd": 0.0,
            }
        )
    return items


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, dict):
        maybe = data.get("items")
        if isinstance(maybe, list):
            return maybe
    if isinstance(data, list):
        return data
    return []


def _assistant_text_from_response(data: Any) -> str:
    if isinstance(data, dict):
        direct = data.get("response")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        nested = (data.get("assistant_message") or {}).get("content")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def call_ollama_chat(*, model: str, messages: list[dict[str, str]]) -> str:
    payload = {"model": model, "messages": messages, "stream": False}
    try:
        parsed = _http_json(method="POST", url=f"{_ollama_base_url()}/api/chat", payload=payload, timeout=120)
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Ollama HTTP {exc.code}: {detail[:400]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar a Ollama: {exc}") from exc

    content = ((parsed.get("message") or {}).get("content") if isinstance(parsed, dict) else None) or (
        parsed.get("response") if isinstance(parsed, dict) else None
    )
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="Ollama no devolvió contenido")
    return content.strip()


app = FastAPI(title="OpenClaw Runtime Bridge", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    try:
        ensure_tables()
        logger.info("Runtime bridge listo con tablas locales")
    except Exception as exc:  # pragma: no cover - startup guard
        logger.warning("No se pudieron inicializar tablas locales: %s", exc)


@app.get("/runtime/integration/status")
def runtime_integration_status() -> dict[str, Any]:
    _refresh_openapi_cache()
    ledger_available = False
    try:
        ledger_available = _table_exists("mem_audit", "execution_ledger")
    except Exception:
        ledger_available = False
    return {
        "openclaw_base_url": _OPENAPI_CACHE.get("base_url") or _openclaw_base_url(),
        "openclaw_base_candidates": _openclaw_base_candidates(),
        "ollama_base_url": _ollama_base_url(),
        "openclaw_paths_detected": sorted(list(_OPENAPI_CACHE.get("paths") or set())),
        "psycopg_available": psycopg is not None,
        "execution_ledger_available": ledger_available,
    }


@app.get("/runtime/chat/history/{agent_id}")
def get_chat_history(agent_id: str, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    remote = _proxy_openclaw(
        key="chat_history",
        method="GET",
        path_params={"agent_id": agent_id},
        query_params={"limit": limit},
    )
    remote_items = _extract_items(remote)
    if remote_items:
        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(remote_items, start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "id": item.get("id", idx),
                    "agent_id": item.get("agent_id") or agent_id,
                    "role": item.get("role", "assistant"),
                    "content": item.get("content") or item.get("message") or "",
                    "source": item.get("source", SOURCE_PROXY),
                    "execution_id": item.get("execution_id"),
                    "created_at": item.get("created_at") or item.get("timestamp"),
                }
            )
        return {"agent_id": agent_id, "items": normalized}

    try:
        ensure_tables()
        return {"agent_id": agent_id, "items": fetch_chat_history_local(agent_id=agent_id, limit=limit)}
    except Exception as exc:
        logger.warning("Fallback sin DB en chat history: %s", exc)
        return {"agent_id": agent_id, "items": []}


@app.get("/runtime/chat/agents")
def get_chat_agents() -> dict[str, Any]:
    remote = _proxy_openclaw(key="chat_agents", method="GET")
    remote_items = _extract_items(remote)
    if remote_items:
        return {"items": remote_items}

    try:
        ensure_tables()
        capabilities = load_agent_capabilities()
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (agent_id)
                        agent_id, role, content, source, execution_id, created_at
                    FROM mem_audit.chat_messages
                    ORDER BY agent_id, created_at DESC, id DESC
                    """
                )
                latest_rows = cur.fetchall()
    except Exception as exc:
        logger.warning("Fallback sin DB en chat agents: %s", exc)
        items = [
            {
                "agent_id": agent_id,
                "model": _resolve_agent_model(load_agent_capabilities().get(agent_id, {})),
                "last_message": None,
                "last_message_at": None,
            }
            for agent_id in DEFAULT_AGENT_IDS
        ]
        return {"items": items}

    latest_by_agent: dict[str, dict[str, Any]] = {}
    for row in latest_rows:
        latest_by_agent[row[0]] = {
            "role": row[1],
            "content": row[2],
            "source": row[3],
            "execution_id": row[4],
            "created_at": _to_iso(row[5]),
        }

    ledger_agent_ids = {
        str(_first_non_empty(row, ("agent_id", "agent", "owner"), "") or "").strip()
        for row in fetch_execution_ledger_rows(limit=300)
    }
    ledger_agent_ids.discard("")
    all_ids = sorted(set(capabilities.keys()) | set(latest_by_agent.keys()) | ledger_agent_ids)
    items: list[dict[str, Any]] = []
    for agent_id in all_ids:
        cfg = capabilities.get(agent_id, {})
        model = _resolve_agent_model(cfg)
        latest = latest_by_agent.get(agent_id)
        items.append(
            {
                "agent_id": agent_id,
                "model": model,
                "last_message": latest,
                "last_message_at": latest.get("created_at") if latest else None,
            }
        )
    items.sort(key=lambda x: (x.get("last_message_at") is None, x.get("last_message_at") or "", x["agent_id"]))
    return {"items": items}


@app.post("/runtime/chat")
def post_chat(payload: ChatRequest) -> dict[str, Any]:
    source = (payload.source or SOURCE_UI).strip().lower()
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser 'ui', 'telegram' o 'proxy'")

    agent_id = payload.agent_id.strip()
    message = payload.message.strip()
    if not agent_id or not message:
        raise HTTPException(status_code=400, detail="agent_id y message son requeridos")

    execution_id = payload.execution_id or str(uuid.uuid4())

    user_row = {
        "id": None,
        "agent_id": agent_id,
        "role": "user",
        "content": message,
        "source": source,
        "execution_id": execution_id,
        "created_at": _to_iso(_utc_now()),
    }
    local_db_ok = True
    try:
        ensure_tables()
        user_row = insert_chat_message(
            agent_id=agent_id,
            role="user",
            content=message,
            source=source,
            execution_id=execution_id,
        )
        upsert_runtime_execution(
            execution_id=execution_id,
            agent_id=agent_id,
            title=f"Chat with {agent_id}",
            description=message[:240],
            status="RUNNING",
            source=source,
            payload={"type": "chat", "message": message},
        )
        insert_runtime_event(
            event_type="chat_user_message",
            agent_id=agent_id,
            execution_id=execution_id,
            status="RUNNING",
            source=source,
            payload={"message": message},
        )
    except Exception as exc:
        local_db_ok = False
        logger.warning("No se pudo persistir user chat en DB local: %s", exc)

    proxy_payload = {
        "agent_id": agent_id,
        "message": message,
        "source": source,
        "execution_id": execution_id,
    }
    remote = _proxy_openclaw(key="chat_post", method="POST", payload=proxy_payload)
    assistant_text = _assistant_text_from_response(remote)

    if not assistant_text:
        capabilities = load_agent_capabilities()
        agent_cfg = capabilities.get(agent_id, {})
        model = _resolve_agent_model(agent_cfg)
        system_prompt = _resolve_prompt(agent_id, agent_cfg)
        history_rows: list[dict[str, Any]] = []
        if local_db_ok:
            try:
                history_rows = fetch_chat_history_local(agent_id=agent_id, limit=CHAT_CONTEXT_LIMIT)
            except Exception:
                history_rows = []
        model_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for row in history_rows:
            if row["role"] in {"user", "assistant"}:
                model_messages.append({"role": row["role"], "content": row["content"]})
        assistant_text = call_ollama_chat(model=model, messages=model_messages)
    else:
        model = "openclaw-proxy"

    assistant_row = {
        "id": None,
        "agent_id": agent_id,
        "role": "assistant",
        "content": assistant_text,
        "source": source,
        "execution_id": execution_id,
        "created_at": _to_iso(_utc_now()),
    }
    if local_db_ok:
        try:
            assistant_row = insert_chat_message(
                agent_id=agent_id,
                role="assistant",
                content=assistant_text,
                source=source,
                execution_id=execution_id,
            )
            upsert_runtime_execution(
                execution_id=execution_id,
                agent_id=agent_id,
                title=f"Chat with {agent_id}",
                description=message[:240],
                status="DONE",
                source=source,
                payload={"type": "chat", "response": assistant_text[:1000]},
            )
            insert_runtime_event(
                event_type="chat_assistant_message",
                agent_id=agent_id,
                execution_id=execution_id,
                status="DONE",
                source=source,
                payload={"message": assistant_text},
            )
        except Exception as exc:
            logger.warning("No se pudo persistir assistant chat en DB local: %s", exc)

    return {
        "agent_id": agent_id,
        "execution_id": execution_id,
        "model": model,
        "source": source,
        "response": assistant_text,
        "user_message": user_row,
        "assistant_message": assistant_row,
    }


@app.get("/runtime/permission/stats")
def permission_stats() -> dict[str, Any]:
    remote = _proxy_openclaw(key="permission_stats", method="GET")
    if isinstance(remote, dict):
        return remote
    try:
        ensure_tables()
        return compute_permission_stats_local()
    except Exception as exc:
        logger.warning("Fallback sin DB en permission stats: %s", exc)
        return {"active_tokens": 0}


@app.get("/runtime/permission/recent")
def permission_recent(limit: int = Query(default=120, ge=1, le=1000)) -> dict[str, Any]:
    remote = _proxy_openclaw(key="permission_recent", method="GET", query_params={"limit": limit})
    remote_items = _extract_items(remote)
    if remote_items:
        return {"items": remote_items}
    try:
        ensure_tables()
        return {"items": fetch_recent_events_local(limit=limit)}
    except Exception as exc:
        logger.warning("Fallback sin DB en permission recent: %s", exc)
        return {"items": []}


@app.get("/runtime/agents/state")
def agents_state() -> dict[str, Any]:
    remote = _proxy_openclaw(key="agents_state", method="GET")
    remote_items = _extract_items(remote)
    if remote_items:
        return {"items": remote_items}
    try:
        ensure_tables()
        return {"items": compute_agents_state_local()}
    except Exception as exc:
        logger.warning("Fallback sin DB en agents state: %s", exc)
        return {"items": [{"agent_id": aid, "state": "idle", "status": "IDLE", "cost_usd": 0.0} for aid in DEFAULT_AGENT_IDS]}


@app.get("/runtime/executions")
def runtime_executions(limit: int = Query(default=60, ge=1, le=1000)) -> dict[str, Any]:
    remote = _proxy_openclaw(key="executions", method="GET", query_params={"limit": limit})
    remote_items = _extract_items(remote)
    if remote_items:
        return {"items": remote_items}
    try:
        ensure_tables()
        return {"items": fetch_executions_local(limit=limit)}
    except Exception as exc:
        logger.warning("Fallback sin DB en executions: %s", exc)
        return {"items": []}


@app.get("/runtime/status/{execution_id}")
def runtime_status(execution_id: str) -> dict[str, Any]:
    remote = _proxy_openclaw(key="status", method="GET", path_params={"execution_id": execution_id})
    if isinstance(remote, dict) and remote:
        if "item" in remote:
            return remote
        return {"item": remote}
    try:
        ensure_tables()
        item = fetch_execution_local(execution_id)
        if not item:
            raise HTTPException(status_code=404, detail="Execution no encontrada")
        return {"item": item}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Fallback sin DB en status: %s", exc)
        raise HTTPException(status_code=404, detail="Execution no encontrada") from exc


def _apply_approval(payload: ApprovalRequest, force_approved: bool | None = None) -> dict[str, Any]:
    approved = bool(payload.approved if force_approved is None else force_approved)
    status = "APPROVED" if approved else "REJECTED"
    source = (payload.source or SOURCE_UI).strip().lower() or SOURCE_UI

    remote_key = "approve" if approved else "reject"
    remote = _proxy_openclaw(
        key=remote_key,
        method="POST",
        payload={
            "execution_id": payload.execution_id,
            "approved": approved,
            "reason": payload.reason,
        },
    )

    try:
        ensure_tables()
        current = fetch_execution_local(payload.execution_id)
        upsert_runtime_execution(
            execution_id=payload.execution_id,
            agent_id=(current or {}).get("agent_id"),
            title=(current or {}).get("title"),
            description=(current or {}).get("description") or payload.reason,
            status=status,
            source=source,
            payload={"approval_reason": payload.reason, "approved": approved},
        )
        insert_runtime_event(
            event_type="approval_decision",
            agent_id=(current or {}).get("agent_id"),
            execution_id=payload.execution_id,
            status=status,
            source=source,
            payload={"reason": payload.reason, "approved": approved},
        )
    except Exception as exc:
        logger.warning("No se pudo persistir aprobación local: %s", exc)

    response = {
        "execution_id": payload.execution_id,
        "approved": approved,
        "status": status,
        "source": source,
    }
    if isinstance(remote, dict):
        response["proxy_result"] = remote
    return response


@app.post("/runtime/approve")
def runtime_approve(payload: ApprovalRequest) -> dict[str, Any]:
    return _apply_approval(payload, force_approved=True)


@app.post("/runtime/reject")
def runtime_reject(payload: ApprovalRequest) -> dict[str, Any]:
    return _apply_approval(payload, force_approved=False)


@app.post("/runtime/events/ingest")
def runtime_events_ingest(payload: RuntimeEventIngest) -> dict[str, Any]:
    try:
        ensure_tables()
        ts = None
        if payload.created_at:
            try:
                ts = datetime.fromisoformat(payload.created_at.replace("Z", "+00:00"))
            except ValueError:
                ts = _utc_now()
        insert_runtime_event(
            event_type=payload.event_type,
            agent_id=payload.agent_id,
            execution_id=payload.execution_id,
            status=_normalize_status(payload.status),
            source=payload.source,
            payload=payload.payload or {},
            created_at=ts,
        )
        if payload.execution_id:
            upsert_runtime_execution(
                execution_id=payload.execution_id,
                agent_id=payload.agent_id,
                title=(payload.payload or {}).get("title"),
                description=(payload.payload or {}).get("description"),
                status=_normalize_status(payload.status),
                source=payload.source,
                payload=payload.payload or {},
            )
    except Exception as exc:
        logger.warning("No se pudo ingerir evento localmente: %s", exc)
        return {"ok": False, "error": str(exc)}

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RUNTIME_HOST", "0.0.0.0"),
        port=int(os.getenv("RUNTIME_PORT", "8001")),
        reload=False,
    )
