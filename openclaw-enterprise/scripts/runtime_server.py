from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    import websockets
except Exception:  # pragma: no cover - optional dependency fallback
    websockets = None

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None


logger = logging.getLogger("openclaw.runtime.chat")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

APP_ROOT = Path(__file__).resolve().parents[1]
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
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
CHAT_CONTEXT_LIMIT = int(os.getenv("CHAT_CONTEXT_LIMIT", "20"))
RUNTIME_CHAT_BACKEND = os.getenv("RUNTIME_CHAT_BACKEND", "gateway").strip().lower()
RUNTIME_CHAT_FALLBACK_OLLAMA = os.getenv("RUNTIME_CHAT_FALLBACK_OLLAMA", "0").strip() == "1"

GATEWAY_WS_URL = os.getenv("GATEWAY_WS_URL", "ws://127.0.0.1:18789").strip()
GATEWAY_AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN", "").strip()
GATEWAY_CONNECT_TIMEOUT_S = float(os.getenv("GATEWAY_CONNECT_TIMEOUT_S", "12"))
GATEWAY_CHAT_TIMEOUT_S = float(os.getenv("GATEWAY_CHAT_TIMEOUT_S", "180"))
GATEWAY_SCOPES = tuple(
    scope.strip()
    for scope in os.getenv(
        "GATEWAY_SCOPES",
        "operator.read,operator.write,operator.admin",
    ).split(",")
    if scope.strip()
)
GATEWAY_SESSION_PREFIX = os.getenv("GATEWAY_SESSION_PREFIX", "mc:agent:").strip()
GATEWAY_FIXED_SESSION_KEY = os.getenv("GATEWAY_SESSION_KEY", "").strip()

SOURCE_UI = "ui"
SOURCE_TELEGRAM = "telegram"
VALID_SOURCES = {SOURCE_UI, SOURCE_TELEGRAM}


class ChatRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source: str = Field(default=SOURCE_UI)
    execution_id: str | None = None


def _db_connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5433")),
        user=os.getenv("PGUSER", "aiadmin"),
        password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "openclaw"),
        autocommit=False,
    )


def ensure_chat_table() -> None:
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
                CREATE INDEX IF NOT EXISTS idx_chat_messages_agent_created_at
                ON mem_audit.chat_messages(agent_id, created_at DESC);
                """
            )
        conn.commit()


def ensure_runtime_tables() -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS mem_audit;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_executions (
                  execution_id TEXT PRIMARY KEY,
                  agent_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  title TEXT NOT NULL DEFAULT 'Execution',
                  description TEXT NOT NULL DEFAULT '',
                  source TEXT NOT NULL DEFAULT 'ui',
                  model TEXT,
                  response TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_events (
                  id BIGSERIAL PRIMARY KEY,
                  execution_id TEXT,
                  agent_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  reason TEXT NOT NULL DEFAULT '',
                  source TEXT NOT NULL DEFAULT 'ui',
                  meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                  timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_agent_state (
                  agent_id TEXT PRIMARY KEY,
                  state TEXT NOT NULL DEFAULT 'idle',
                  cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                  last_execution_id TEXT,
                  last_status TEXT,
                  last_reason TEXT,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_events_timestamp
                ON mem_audit.runtime_events(timestamp DESC, id DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_events_agent_timestamp
                ON mem_audit.runtime_events(agent_id, timestamp DESC, id DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_executions_updated_at
                ON mem_audit.runtime_executions(updated_at DESC);
                """
            )
        conn.commit()


def _clip_text(value: str, max_chars: int = 350) -> str:
    compact = " ".join(str(value).split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def _extract_agent_mapping(raw_data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_data, dict):
        return {}

    root: Any = raw_data
    if isinstance(raw_data.get("agents"), dict):
        root = raw_data["agents"]
    elif isinstance(raw_data.get("agent_capabilities"), dict):
        root = raw_data["agent_capabilities"]
    elif isinstance(raw_data.get("capabilities"), dict):
        root = raw_data["capabilities"]

    out: dict[str, dict[str, Any]] = {}
    if isinstance(root, dict):
        for agent_id, cfg in root.items():
            if not isinstance(agent_id, str):
                continue
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
    return DEFAULT_OLLAMA_MODEL


def _resolve_prompt(agent_id: str, agent_cfg: dict[str, Any]) -> str:
    for key in ("system_prompt", "prompt", "instructions"):
        value = agent_cfg.get(key)
        if isinstance(value, str) and value.strip():
            trimmed = value.strip()
            # Si contiene saltos de línea asumimos prompt inline.
            if "\n" in trimmed:
                return trimmed
            # Si apunta a archivo, intentamos cargarlo.
            possible_path = (APP_ROOT / trimmed).resolve() if not Path(trimmed).is_absolute() else Path(trimmed)
            if possible_path.exists():
                return possible_path.read_text(encoding="utf-8")

    for key in ("prompt_file", "system_prompt_file", "prompt_path"):
        value = agent_cfg.get(key)
        if isinstance(value, str) and value.strip():
            possible_path = (APP_ROOT / value.strip()).resolve() if not Path(value).is_absolute() else Path(value)
            if possible_path.exists():
                return possible_path.read_text(encoding="utf-8")

    for candidate in (
        PROMPTS_DIR / f"{agent_id}.md",
        PROMPTS_DIR / f"{agent_id.replace('_', '-')}.md",
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    return (
        f"You are OpenClaw agent '{agent_id}'. "
        "Follow user instructions safely and provide concise, actionable answers."
    )


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _agent_row_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    ts = item.get("last_message_at")
    if not ts:
        return (1, 0.0, str(item.get("agent_id") or ""))
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (0, -parsed.timestamp(), str(item.get("agent_id") or ""))
    except ValueError:
        return (0, 0.0, str(item.get("agent_id") or ""))


def fetch_chat_history(agent_id: str, limit: int) -> list[dict[str, Any]]:
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

    # Mantener orden cronológico ascendente para rendering de chat.
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


def insert_chat_message(
    *,
    agent_id: str,
    role: str,
    content: str,
    source: str,
    execution_id: str | None,
) -> dict[str, Any]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.chat_messages (agent_id, role, content, source, execution_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (agent_id, role, content, source, execution_id),
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


def upsert_runtime_execution(
    *,
    execution_id: str,
    agent_id: str,
    status: str,
    title: str,
    description: str,
    source: str,
    model: str | None = None,
    response: str | None = None,
) -> dict[str, Any]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_executions (
                    execution_id, agent_id, status, title, description, source, model, response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (execution_id) DO UPDATE
                SET
                    agent_id = EXCLUDED.agent_id,
                    status = EXCLUDED.status,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    source = EXCLUDED.source,
                    model = COALESCE(EXCLUDED.model, mem_audit.runtime_executions.model),
                    response = COALESCE(EXCLUDED.response, mem_audit.runtime_executions.response),
                    updated_at = now()
                RETURNING execution_id, agent_id, status, title, description, source, model, response, created_at, updated_at
                """,
                (execution_id, agent_id, status, title, description, source, model, response),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "execution_id": row[0],
        "agent_id": row[1],
        "status": row[2],
        "title": row[3],
        "description": row[4],
        "source": row[5],
        "model": row[6],
        "response": row[7],
        "created_at": _to_iso(row[8]),
        "updated_at": _to_iso(row[9]),
    }


def insert_runtime_event(
    *,
    execution_id: str | None,
    agent_id: str,
    status: str,
    reason: str,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_events (execution_id, agent_id, status, reason, source, meta)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, timestamp
                """,
                (execution_id, agent_id, status, reason, source, json.dumps(meta or {})),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "id": row[0],
        "execution_id": execution_id,
        "agent_id": agent_id,
        "status": status,
        "reason": reason,
        "source": source,
        "meta": meta or {},
        "timestamp": _to_iso(row[1]),
    }


def upsert_runtime_agent_state(
    *,
    agent_id: str,
    state: str,
    last_execution_id: str | None,
    last_status: str | None,
    last_reason: str | None,
) -> dict[str, Any]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_agent_state (
                    agent_id, state, last_execution_id, last_status, last_reason
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (agent_id) DO UPDATE
                SET
                    state = EXCLUDED.state,
                    last_execution_id = EXCLUDED.last_execution_id,
                    last_status = EXCLUDED.last_status,
                    last_reason = EXCLUDED.last_reason,
                    updated_at = now()
                RETURNING agent_id, state, cost_usd, last_execution_id, last_status, last_reason, updated_at
                """,
                (agent_id, state, last_execution_id, last_status, last_reason),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "agent_id": row[0],
        "state": row[1],
        "cost_usd": float(row[2] or 0),
        "last_execution_id": row[3],
        "last_status": row[4],
        "last_reason": row[5],
        "updated_at": _to_iso(row[6]),
    }


def fetch_recent_runtime_events(limit: int) -> list[dict[str, Any]]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, execution_id, agent_id, status, reason, source, meta, timestamp
                FROM mem_audit.runtime_events
                ORDER BY timestamp DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    rows.reverse()
    return [
        {
            "id": row[0],
            "token_id": row[1],
            "execution_id": row[1],
            "agent_id": row[2],
            "status": row[3],
            "state": row[3],
            "reason": row[4],
            "action": row[4],
            "decision_reason": row[4],
            "source": row[5],
            "meta": row[6] if isinstance(row[6], dict) else {},
            "timestamp": _to_iso(row[7]),
        }
        for row in rows
    ]


def fetch_runtime_executions(limit: int) -> list[dict[str, Any]]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT execution_id, agent_id, status, title, description, source, model, response, created_at, updated_at
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
            "id": row[0],
            "agent_id": row[1],
            "status": row[2],
            "state": row[2],
            "title": row[3],
            "description": row[4],
            "source": row[5],
            "model": row[6],
            "response": row[7],
            "cost_usd": 0.0,
            "created_at": _to_iso(row[8]),
            "updated_at": _to_iso(row[9]),
        }
        for row in rows
    ]


def fetch_runtime_execution(execution_id: str) -> dict[str, Any] | None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT execution_id, agent_id, status, title, description, source, model, response, created_at, updated_at
                FROM mem_audit.runtime_executions
                WHERE execution_id = %s
                """,
                (execution_id,),
            )
            row = cur.fetchone()

    if row is None:
        return None
    return {
        "execution_id": row[0],
        "id": row[0],
        "agent_id": row[1],
        "status": row[2],
        "state": row[2],
        "title": row[3],
        "description": row[4],
        "source": row[5],
        "model": row[6],
        "response": row[7],
        "cost_usd": 0.0,
        "created_at": _to_iso(row[8]),
        "updated_at": _to_iso(row[9]),
    }


def fetch_runtime_agent_states() -> list[dict[str, Any]]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT agent_id, state, cost_usd, last_execution_id, last_status, last_reason, updated_at
                FROM mem_audit.runtime_agent_state
                ORDER BY agent_id ASC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "agent_id": row[0],
            "state": row[1],
            "cost_usd": float(row[2] or 0),
            "last_execution_id": row[3],
            "last_status": row[4],
            "last_reason": row[5],
            "updated_at": _to_iso(row[6]),
        }
        for row in rows
    ]


def count_active_runtime_tokens() -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM mem_audit.runtime_executions
                WHERE UPPER(status) IN ('RUNNING', 'IN_PROGRESS', 'PROPOSED', 'HITL_WAIT', 'STARTED')
                """
            )
            row = cur.fetchone()
    return int(row[0] or 0)


def call_ollama_chat(*, model: str, messages: list[dict[str, str]]) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    payload = {"model": model, "messages": messages, "stream": False}
    req = urllib_request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=502,
            detail=f"Ollama HTTP {exc.code}: {detail[:400]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar a Ollama: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Respuesta inválida desde Ollama") from exc

    content = (
        (parsed.get("message") or {}).get("content")
        or parsed.get("response")
        or ""
    )
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="Ollama no devolvió contenido")
    return content.strip()


def _extract_assistant_text(message: Any) -> str:
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "text":
                    continue
                block_text = block.get("text")
                if isinstance(block_text, str) and block_text.strip():
                    parts.append(block_text.strip())
            merged = "\n".join(parts).strip()
            if merged:
                return merged
    return ""


def _normalize_gateway_frame(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _resolve_gateway_session_key(agent_id: str) -> str:
    if GATEWAY_FIXED_SESSION_KEY:
        return GATEWAY_FIXED_SESSION_KEY
    return f"{GATEWAY_SESSION_PREFIX}{agent_id}"


async def _gateway_wait_response(
    ws: Any,
    *,
    request_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise HTTPException(status_code=504, detail=f"Timeout esperando respuesta del gateway ({request_id})")
        raw_frame = await asyncio.wait_for(ws.recv(), timeout=remaining)
        frame = _normalize_gateway_frame(raw_frame)
        if not frame:
            continue
        if frame.get("type") == "res" and str(frame.get("id") or "") == request_id:
            return frame


async def call_gateway_chat(
    *,
    agent_id: str,
    message: str,
    execution_id: str,
) -> dict[str, Any]:
    if websockets is None:
        raise HTTPException(
            status_code=500,
            detail="Dependencia 'websockets' no instalada. Instala requirements-runtime.txt",
        )
    if not GATEWAY_WS_URL:
        raise HTTPException(status_code=500, detail="GATEWAY_WS_URL no configurado")

    session_key = _resolve_gateway_session_key(agent_id)
    connect_req_id = str(uuid.uuid4())
    chat_req_id = str(uuid.uuid4())
    scopes = list(GATEWAY_SCOPES) if GATEWAY_SCOPES else ["operator.read", "operator.write"]
    connect_payload: dict[str, Any] = {
        "minProtocol": 3,
        "maxProtocol": 3,
        "client": {
            "id": "mission-control-runtime",
            "displayName": "Mission Control Runtime Bridge",
            "version": "1.0.0",
            "platform": "python",
            "mode": "ui",
            "instanceId": "mission-control-runtime",
        },
        "locale": "es-ES",
        "userAgent": "mission-control-runtime/1.0.0",
        "role": "operator",
        "scopes": scopes,
        "caps": [],
    }
    if GATEWAY_AUTH_TOKEN:
        connect_payload["auth"] = {"token": GATEWAY_AUTH_TOKEN}

    try:
        async with websockets.connect(
            GATEWAY_WS_URL,
            open_timeout=GATEWAY_CONNECT_TIMEOUT_S,
            close_timeout=8,
            max_size=2_000_000,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": connect_req_id,
                        "method": "connect",
                        "params": connect_payload,
                    }
                )
            )
            connect_res = await _gateway_wait_response(
                ws,
                request_id=connect_req_id,
                timeout_s=GATEWAY_CONNECT_TIMEOUT_S,
            )
            if not bool(connect_res.get("ok")):
                err = connect_res.get("error")
                raise HTTPException(status_code=502, detail=f"Gateway connect rechazado: {err}")

            await ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": chat_req_id,
                        "method": "chat.send",
                        "params": {
                            "sessionKey": session_key,
                            "message": message,
                            "deliver": False,
                            "idempotencyKey": execution_id,
                        },
                    }
                )
            )
            chat_send_res = await _gateway_wait_response(ws, request_id=chat_req_id, timeout_s=20)
            if not bool(chat_send_res.get("ok")):
                err = chat_send_res.get("error")
                raise HTTPException(status_code=502, detail=f"Gateway chat.send rechazado: {err}")

            ack_payload = chat_send_res.get("payload") or {}
            run_id = (
                ack_payload.get("runId")
                if isinstance(ack_payload, dict)
                else None
            ) or execution_id

            loop = asyncio.get_running_loop()
            deadline = loop.time() + GATEWAY_CHAT_TIMEOUT_S
            buffered_text = ""
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise HTTPException(status_code=504, detail=f"Gateway chat timeout run_id={run_id}")
                frame_raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                frame = _normalize_gateway_frame(frame_raw)
                if not frame or frame.get("type") != "event" or frame.get("event") != "chat":
                    continue

                payload = frame.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_run_id = str(payload.get("runId") or "")
                if payload_run_id and payload_run_id != run_id:
                    continue
                payload_session_key = str(payload.get("sessionKey") or "")
                if payload_session_key and payload_session_key != session_key:
                    continue

                state = str(payload.get("state") or "").lower()
                message_text = _extract_assistant_text(payload.get("message"))
                if state == "delta":
                    if message_text and len(message_text) >= len(buffered_text):
                        buffered_text = message_text
                    continue
                if state == "final":
                    final_text = (message_text or buffered_text).strip()
                    if not final_text:
                        raise HTTPException(status_code=502, detail="Gateway devolvió final sin texto")
                    return {
                        "text": final_text,
                        "state": "final",
                        "run_id": run_id,
                        "session_key": session_key,
                        "raw_payload": payload,
                    }
                if state == "aborted":
                    partial = (message_text or buffered_text).strip()
                    if partial:
                        return {
                            "text": partial,
                            "state": "aborted",
                            "run_id": run_id,
                            "session_key": session_key,
                            "raw_payload": payload,
                        }
                    raise HTTPException(status_code=502, detail="Gateway abortó la ejecución sin texto")
                if state == "error":
                    detail = str(payload.get("errorMessage") or "error sin detalle")
                    raise HTTPException(status_code=502, detail=f"Gateway chat error: {detail}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error conectando con gateway WS: {exc}") from exc


app = FastAPI(title="OpenClaw Runtime Server", version="1.0.0")
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
        ensure_chat_table()
        ensure_runtime_tables()
        logger.info("Tabla mem_audit.chat_messages lista")
    except Exception as exc:  # pragma: no cover - startup guard
        logger.exception("Error inicializando tabla de chat: %s", exc)


@app.get("/runtime/chat/history/{agent_id}")
def get_chat_history(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    try:
        ensure_chat_table()
        items = fetch_chat_history(agent_id=agent_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo historial: {exc}") from exc
    return {"agent_id": agent_id, "items": items}


@app.get("/runtime/chat/agents")
def get_chat_agents() -> dict[str, Any]:
    try:
        ensure_chat_table()
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
        raise HTTPException(status_code=500, detail=f"Error listando agentes: {exc}") from exc

    latest_by_agent: dict[str, dict[str, Any]] = {}
    for row in latest_rows:
        latest_by_agent[row[0]] = {
            "role": row[1],
            "content": row[2],
            "source": row[3],
            "execution_id": row[4],
            "created_at": _to_iso(row[5]),
        }

    all_ids = sorted(set(capabilities.keys()) | set(latest_by_agent.keys()))
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

    items.sort(key=_agent_row_sort_key)
    return {"items": items}


@app.get("/runtime/permission/stats")
def get_permission_stats() -> dict[str, Any]:
    try:
        ensure_runtime_tables()
        active_tokens = count_active_runtime_tokens()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo stats runtime: {exc}") from exc
    return {"active_tokens": active_tokens}


@app.get("/runtime/permission/recent")
def get_permission_recent(
    limit: int = Query(default=120, ge=1, le=500),
) -> dict[str, Any]:
    try:
        ensure_runtime_tables()
        items = fetch_recent_runtime_events(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo eventos runtime: {exc}") from exc
    return {"items": items}


@app.get("/runtime/executions")
def get_runtime_executions(
    limit: int = Query(default=60, ge=1, le=500),
) -> dict[str, Any]:
    try:
        ensure_runtime_tables()
        items = fetch_runtime_executions(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo ejecuciones runtime: {exc}") from exc
    return {"items": items}


@app.get("/runtime/status/{execution_id}")
def get_runtime_status(execution_id: str) -> dict[str, Any]:
    try:
        ensure_runtime_tables()
        item = fetch_runtime_execution(execution_id=execution_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo estado runtime: {exc}") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="execution_id no encontrado")
    return {"item": item}


@app.get("/runtime/agents/state")
def get_runtime_agents_state() -> dict[str, Any]:
    try:
        ensure_runtime_tables()
        capabilities = load_agent_capabilities()
        rows = fetch_runtime_agent_states()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo estado de agentes: {exc}") from exc

    by_agent = {row["agent_id"]: row for row in rows}
    all_ids = sorted(set(capabilities.keys()) | set(by_agent.keys()))
    items: list[dict[str, Any]] = []
    for agent_id in all_ids:
        row = by_agent.get(agent_id)
        items.append(
            {
                "agent_id": agent_id,
                "state": (row or {}).get("state", "idle"),
                "cost_usd": float((row or {}).get("cost_usd", 0) or 0),
                "last_execution_id": (row or {}).get("last_execution_id"),
                "last_status": (row or {}).get("last_status"),
                "last_reason": (row or {}).get("last_reason"),
                "updated_at": (row or {}).get("updated_at"),
            }
        )
    return {"items": items}


@app.post("/runtime/chat")
async def post_chat(payload: ChatRequest) -> dict[str, Any]:
    agent_id = payload.agent_id.strip()
    message = payload.message.strip()
    source = payload.source.strip().lower() if payload.source else SOURCE_UI

    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser 'ui' o 'telegram'")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id requerido")
    if not message:
        raise HTTPException(status_code=400, detail="message requerido")

    execution_id = payload.execution_id or str(uuid.uuid4())
    capabilities = load_agent_capabilities()
    agent_cfg = capabilities.get(agent_id, {})
    model = _resolve_agent_model(agent_cfg)
    system_prompt = _resolve_prompt(agent_id, agent_cfg)

    try:
        ensure_chat_table()
        ensure_runtime_tables()
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
            status="RUNNING",
            title=f"{agent_id} mission",
            description=_clip_text(message, 500),
            source=source,
            model=model,
        )
        insert_runtime_event(
            execution_id=execution_id,
            agent_id=agent_id,
            status="RUNNING",
            reason=_clip_text(message),
            source=source,
            meta={"phase": "user_message"},
        )
        upsert_runtime_agent_state(
            agent_id=agent_id,
            state="working",
            last_execution_id=execution_id,
            last_status="RUNNING",
            last_reason=_clip_text(message, 240),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error persistiendo mensaje: {exc}") from exc

    assistant_text: str
    runtime_state = "DONE"
    try:
        if RUNTIME_CHAT_BACKEND == "ollama":
            history_rows = fetch_chat_history(agent_id=agent_id, limit=CHAT_CONTEXT_LIMIT)
            messages_for_model: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
            for row in history_rows:
                role = row["role"]
                if role not in {"user", "assistant"}:
                    continue
                messages_for_model.append({"role": role, "content": row["content"]})
            assistant_text = call_ollama_chat(model=model, messages=messages_for_model)
        else:
            gateway_result = await call_gateway_chat(
                agent_id=agent_id,
                message=message,
                execution_id=execution_id,
            )
            assistant_text = str(gateway_result.get("text") or "").strip()
            if not assistant_text:
                raise HTTPException(status_code=502, detail="Gateway devolvió respuesta vacía")
            runtime_state = "DONE" if gateway_result.get("state") == "final" else "FAILED"
    except HTTPException as exc:
        if RUNTIME_CHAT_BACKEND != "ollama" and RUNTIME_CHAT_FALLBACK_OLLAMA:
            logger.warning("Gateway falló; usando fallback a Ollama: %s", exc.detail)
            history_rows = fetch_chat_history(agent_id=agent_id, limit=CHAT_CONTEXT_LIMIT)
            messages_for_model = [{"role": "system", "content": system_prompt}]
            for row in history_rows:
                role = row["role"]
                if role in {"user", "assistant"}:
                    messages_for_model.append({"role": role, "content": row["content"]})
            assistant_text = call_ollama_chat(model=model, messages=messages_for_model)
            runtime_state = "DONE"
        else:
            with contextlib.suppress(Exception):
                upsert_runtime_execution(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    status="FAILED",
                    title=f"{agent_id} mission",
                    description=_clip_text(str(exc.detail), 500),
                    source=source,
                    model=model,
                )
                insert_runtime_event(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    status="FAILED",
                    reason=_clip_text(str(exc.detail)),
                    source=source,
                    meta={"phase": "assistant_error"},
                )
                upsert_runtime_agent_state(
                    agent_id=agent_id,
                    state="idle",
                    last_execution_id=execution_id,
                    last_status="FAILED",
                    last_reason=_clip_text(str(exc.detail), 240),
                )
            raise

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
            status=runtime_state,
            title=f"{agent_id} mission",
            description=_clip_text(message, 500),
            source=source,
            model=model,
            response=_clip_text(assistant_text, 2000),
        )
        insert_runtime_event(
            execution_id=execution_id,
            agent_id=agent_id,
            status=runtime_state,
            reason=_clip_text(assistant_text),
            source=source,
            meta={"phase": "assistant_message"},
        )
        upsert_runtime_agent_state(
            agent_id=agent_id,
            state="idle",
            last_execution_id=execution_id,
            last_status=runtime_state,
            last_reason=_clip_text(assistant_text, 240),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error guardando respuesta: {exc}") from exc

    return {
        "agent_id": agent_id,
        "execution_id": execution_id,
        "model": model,
        "source": source,
        "response": assistant_text,
        "user_message": user_row,
        "assistant_message": assistant_row,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RUNTIME_HOST", "0.0.0.0"),
        port=int(os.getenv("RUNTIME_PORT", "8001")),
        reload=False,
    )
