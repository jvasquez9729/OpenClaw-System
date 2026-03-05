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
from urllib import request as urllib_request

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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

    messages_for_model: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for row in history_rows:
        role = row["role"]
        if role not in {"user", "assistant"}:
            continue
        messages_for_model.append({"role": role, "content": row["content"]})

    assistant_text = call_ollama_chat(model=model, messages=messages_for_model)

    try:
        assistant_row = insert_chat_message(
            agent_id=agent_id,
            role="assistant",
            content=assistant_text,
            source=source,
            execution_id=execution_id,
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
