from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None

try:
    from websockets.sync.client import connect as ws_connect
except Exception:  # pragma: no cover - optional dependency fallback
    ws_connect = None


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
GATEWAY_WS_URL = os.getenv("OPENCLAW_GATEWAY_WS_URL", "ws://127.0.0.1:18789").strip()
GATEWAY_TOKEN = (
    os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    or os.getenv("OPENCLAW_GATEWAY_AUTH_TOKEN", "")
).strip()
GATEWAY_PASSWORD = os.getenv("OPENCLAW_GATEWAY_PASSWORD", "").strip()
GATEWAY_PROTOCOL = int(os.getenv("OPENCLAW_GATEWAY_PROTOCOL", "3"))
GATEWAY_CONNECT_TIMEOUT_S = float(os.getenv("OPENCLAW_GATEWAY_CONNECT_TIMEOUT_S", "8"))
GATEWAY_REQUEST_TIMEOUT_S = float(os.getenv("OPENCLAW_GATEWAY_REQUEST_TIMEOUT_S", "60"))
GATEWAY_CHAT_TIMEOUT_S = float(os.getenv("OPENCLAW_GATEWAY_CHAT_TIMEOUT_S", "180"))
GATEWAY_SCOPES = [
    scope.strip()
    for scope in os.getenv("OPENCLAW_GATEWAY_SCOPES", "operator.read,operator.write").split(",")
    if scope.strip()
]
GATEWAY_SESSION_TEMPLATE = os.getenv("OPENCLAW_GATEWAY_SESSION_TEMPLATE", "agent:{agent_id}:main")
GATEWAY_CLIENT_ID = os.getenv("OPENCLAW_GATEWAY_CLIENT_ID", "openclaw-control-ui").strip()
GATEWAY_CLIENT_MODE = os.getenv("OPENCLAW_GATEWAY_CLIENT_MODE", "ui").strip()
GATEWAY_ENABLED = os.getenv("OPENCLAW_GATEWAY_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
OLLAMA_FALLBACK_ENABLED = os.getenv("OPENCLAW_OLLAMA_FALLBACK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_audit.runtime_events (
                  id BIGSERIAL PRIMARY KEY,
                  execution_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload TEXT NOT NULL DEFAULT '{}',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_events_execution_created_at
                ON mem_audit.runtime_events(execution_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_events_agent_created_at
                ON mem_audit.runtime_events(agent_id, created_at DESC);
                """
            )
        conn.commit()


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


def insert_runtime_event(
    *,
    execution_id: str,
    agent_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mem_audit.runtime_events (execution_id, agent_id, event_type, payload)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    execution_id,
                    agent_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
        conn.commit()


def _insert_runtime_event_safe(
    *,
    execution_id: str,
    agent_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        insert_runtime_event(
            execution_id=execution_id,
            agent_id=agent_id,
            event_type=event_type,
            payload=payload,
        )
    except Exception as exc:  # pragma: no cover - observability guard
        logger.warning("No se pudo persistir runtime_event=%s: %s", event_type, exc)


def _extract_text_from_message(raw_message: Any) -> str:
    if isinstance(raw_message, str):
        return raw_message.strip()
    if not isinstance(raw_message, dict):
        return ""

    text = raw_message.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    content = raw_message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").lower() != "text":
                continue
            part = block.get("text")
            if isinstance(part, str) and part.strip():
                parts.append(part.strip())
        if parts:
            return "\n".join(parts).strip()
    return ""


def _build_gateway_error_message(method: str, error: Any) -> str:
    if not isinstance(error, dict):
        return f"Gateway {method} failed"
    code = str(error.get("code") or "UNKNOWN")
    message = str(error.get("message") or "request failed")
    details = error.get("details")
    detail_text = f" details={details}" if details is not None else ""
    return f"Gateway {method} failed [{code}]: {message}{detail_text}"


def _resolve_gateway_session_key(agent_id: str) -> str:
    template = GATEWAY_SESSION_TEMPLATE or "agent:{agent_id}:main"
    if "{agent_id}" in template:
        return template.format(agent_id=agent_id)
    return template


def _gateway_receive_frame(ws: Any, timeout_s: float) -> dict[str, Any]:
    raw = ws.recv(timeout=timeout_s)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raise RuntimeError("Gateway frame inválido")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gateway devolvió un frame no-JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Gateway devolvió un frame no-object")
    return parsed


def _gateway_request(
    *,
    ws: Any,
    method: str,
    params: dict[str, Any],
    timeout_s: float,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    req_id = str(uuid.uuid4())
    ws.send(
        json.dumps(
            {
                "type": "req",
                "id": req_id,
                "method": method,
                "params": params,
            }
        )
    )
    deadline = time.monotonic() + timeout_s

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Timeout esperando respuesta de {method}")
        frame = _gateway_receive_frame(ws, timeout_s=remaining)
        frame_type = frame.get("type")

        if frame_type == "event":
            if on_event is not None:
                on_event(frame)
            continue

        if frame_type != "res":
            continue
        if frame.get("id") != req_id:
            continue
        if frame.get("ok") is True:
            payload = frame.get("payload")
            return payload if isinstance(payload, dict) else {}
        raise RuntimeError(_build_gateway_error_message(method, frame.get("error")))


def call_openclaw_gateway_chat(
    *,
    agent_id: str,
    message: str,
    execution_id: str,
) -> dict[str, Any]:
    if ws_connect is None:
        raise RuntimeError(
            "Dependencia websockets no disponible. Instala 'websockets' para usar OPENCLAW gateway."
        )

    session_key = _resolve_gateway_session_key(agent_id)
    chat_payload: dict[str, Any] = {}
    latest_delta_text = ""
    expected_run_ids = {execution_id}

    def on_event(frame: dict[str, Any]) -> None:
        nonlocal latest_delta_text
        if frame.get("type") != "event":
            return
        if frame.get("event") != "chat":
            return
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return
        run_id_value = str(payload.get("runId") or "")
        if run_id_value not in expected_run_ids:
            return
        if payload.get("sessionKey") != session_key:
            return
        if payload.get("state") == "delta":
            delta_text = _extract_text_from_message(payload.get("message"))
            if delta_text:
                latest_delta_text = delta_text
        if payload.get("state") in {"final", "error", "aborted"}:
            chat_payload.clear()
            chat_payload.update(payload)

    connect_params: dict[str, Any] = {
        "minProtocol": GATEWAY_PROTOCOL,
        "maxProtocol": GATEWAY_PROTOCOL,
        "client": {
            "id": GATEWAY_CLIENT_ID,
            "version": "mission-control-runtime",
            "platform": "linux",
            "mode": GATEWAY_CLIENT_MODE,
            "instanceId": execution_id,
        },
        "role": "operator",
        "scopes": GATEWAY_SCOPES,
        "caps": [],
        "locale": "es-ES",
        "userAgent": "mission-control-runtime/1.0.0",
    }
    auth_payload: dict[str, str] = {}
    if GATEWAY_TOKEN:
        auth_payload["token"] = GATEWAY_TOKEN
    if GATEWAY_PASSWORD:
        auth_payload["password"] = GATEWAY_PASSWORD
    if auth_payload:
        connect_params["auth"] = auth_payload

    with ws_connect(
        GATEWAY_WS_URL,
        open_timeout=GATEWAY_CONNECT_TIMEOUT_S,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
        max_size=4 * 1024 * 1024,
    ) as ws:
        hello_payload = _gateway_request(
            ws=ws,
            method="connect",
            params=connect_params,
            timeout_s=GATEWAY_REQUEST_TIMEOUT_S,
            on_event=on_event,
        )
        send_payload = _gateway_request(
            ws=ws,
            method="chat.send",
            params={
                "sessionKey": session_key,
                "message": message,
                "deliver": False,
                "idempotencyKey": execution_id,
            },
            timeout_s=GATEWAY_REQUEST_TIMEOUT_S,
            on_event=on_event,
        )
        run_id = str(send_payload.get("runId") or execution_id)
        expected_run_ids.add(run_id)

        # chat.send es no-bloqueante: esperamos el evento chat final/error.
        deadline = time.monotonic() + GATEWAY_CHAT_TIMEOUT_S
        while not chat_payload:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Timeout esperando evento chat final desde OpenClaw gateway")
            frame = _gateway_receive_frame(ws, timeout_s=remaining)
            if frame.get("type") != "event":
                continue
            on_event(frame)

        state = str(chat_payload.get("state") or "").lower()
        if state == "error":
            raise RuntimeError(str(chat_payload.get("errorMessage") or "chat error"))
        if state == "aborted":
            raise RuntimeError("chat abortado por runtime OpenClaw")

        assistant_text = _extract_text_from_message(chat_payload.get("message")) or latest_delta_text
        if not assistant_text:
            history_payload = _gateway_request(
                ws=ws,
                method="chat.history",
                params={"sessionKey": session_key, "limit": 20},
                timeout_s=GATEWAY_REQUEST_TIMEOUT_S,
                on_event=on_event,
            )
            rows = history_payload.get("messages")
            if isinstance(rows, list):
                for row in reversed(rows):
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("role") or "").lower() != "assistant":
                        continue
                    assistant_text = _extract_text_from_message(row)
                    if assistant_text:
                        break
        if not assistant_text:
            raise RuntimeError("OpenClaw gateway no devolvió contenido del asistente")

        return {
            "run_id": run_id,
            "session_key": session_key,
            "hello": hello_payload,
            "send": send_payload,
            "chat": dict(chat_payload),
            "response": assistant_text.strip(),
        }


def _candidate_ollama_base_urls() -> list[str]:
    configured = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if configured:
        return [configured]
    # En Docker Linux, host.docker.internal puede requerir --add-host, por eso
    # también probamos la gateway bridge usual (172.17.0.1).
    return [
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434",
        "http://172.17.0.1:11434",
    ]


def call_ollama_chat(*, model: str, messages: list[dict[str, str]]) -> str:
    payload = {"model": model, "messages": messages, "stream": False}
    attempted_errors: list[str] = []

    for base_url in _candidate_ollama_base_urls():
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
            attempted_errors.append(f"{base_url} -> HTTP {exc.code}: {detail[:160]}")
            continue
        except Exception as exc:
            attempted_errors.append(f"{base_url} -> {exc}")
            continue

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

    detail = " | ".join(attempted_errors[:3]) if attempted_errors else "sin detalles"
    raise HTTPException(status_code=502, detail=f"No se pudo conectar a Ollama: {detail}")


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
        logger.info("Tablas mem_audit.chat_messages y mem_audit.runtime_events listas")
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


@app.post("/runtime/chat")
def post_chat(payload: ChatRequest) -> dict[str, Any]:
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
        user_row = insert_chat_message(
            agent_id=agent_id,
            role="user",
            content=message,
            source=source,
            execution_id=execution_id,
        )
        history_rows = fetch_chat_history(agent_id=agent_id, limit=CHAT_CONTEXT_LIMIT)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error persistiendo mensaje: {exc}") from exc

    _insert_runtime_event_safe(
        execution_id=execution_id,
        agent_id=agent_id,
        event_type="chat.user.received",
        payload={
            "source": source,
            "message_id": user_row.get("id"),
            "message": message,
        },
    )

    assistant_text: str | None = None
    provider = "gateway" if GATEWAY_ENABLED else "ollama"
    response_model = model
    gateway_meta: dict[str, Any] | None = None

    if GATEWAY_ENABLED:
        try:
            gateway_meta = call_openclaw_gateway_chat(
                agent_id=agent_id,
                message=message,
                execution_id=execution_id,
            )
            assistant_text = str(gateway_meta.get("response") or "").strip()
            response_model = "openclaw-gateway"
            _insert_runtime_event_safe(
                execution_id=execution_id,
                agent_id=agent_id,
                event_type="chat.gateway.final",
                payload={
                    "run_id": gateway_meta.get("run_id"),
                    "session_key": gateway_meta.get("session_key"),
                    "state": (gateway_meta.get("chat") or {}).get("state"),
                },
            )
        except Exception as exc:
            logger.exception("Error enviando chat al gateway OpenClaw: %s", exc)
            _insert_runtime_event_safe(
                execution_id=execution_id,
                agent_id=agent_id,
                event_type="chat.gateway.error",
                payload={"error": str(exc)},
            )
            if not OLLAMA_FALLBACK_ENABLED:
                raise HTTPException(status_code=502, detail=f"Error en OpenClaw gateway: {exc}") from exc
            provider = "ollama_fallback"

    if assistant_text is None:
        messages_for_model: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for row in history_rows:
            role = row["role"]
            if role not in {"user", "assistant"}:
                continue
            messages_for_model.append({"role": role, "content": row["content"]})
        assistant_text = call_ollama_chat(model=model, messages=messages_for_model)
        _insert_runtime_event_safe(
            execution_id=execution_id,
            agent_id=agent_id,
            event_type="chat.ollama.final",
            payload={"model": model},
        )

    try:
        assistant_row = insert_chat_message(
            agent_id=agent_id,
            role="assistant",
            content=assistant_text,
            source=source,
            execution_id=execution_id,
        )
        _insert_runtime_event_safe(
            execution_id=execution_id,
            agent_id=agent_id,
            event_type="chat.assistant.persisted",
            payload={
                "message_id": assistant_row.get("id"),
                "provider": provider,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error guardando respuesta: {exc}") from exc

    return {
        "agent_id": agent_id,
        "execution_id": execution_id,
        "model": response_model,
        "provider": provider,
        "source": source,
        "response": assistant_text,
        "user_message": user_row,
        "assistant_message": assistant_row,
        "gateway": {
            "run_id": gateway_meta.get("run_id"),
            "session_key": gateway_meta.get("session_key"),
        }
        if gateway_meta
        else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RUNTIME_HOST", "0.0.0.0"),
        port=int(os.getenv("RUNTIME_PORT", "8001")),
        reload=False,
    )
