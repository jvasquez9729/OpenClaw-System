from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("openclaw.telegram.bot")

RUNTIME_BASE_URL = os.getenv("RUNTIME_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _http_get_json(url: str) -> dict:
    req = urllib_request.Request(url, method="GET")
    with urllib_request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict) -> dict:
    req = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib_request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "OpenClaw Telegram bot activo.\n\n"
        "Comandos:\n"
        "/agents - lista agentes disponibles\n"
        "/chat <agent_id> <mensaje> - envía instrucción al agente"
    )


async def agents_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        data = await asyncio.to_thread(
            _http_get_json,
            f"{RUNTIME_BASE_URL}/runtime/chat/agents",
        )
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        await update.message.reply_text(f"Error consultando agentes: HTTP {exc.code} {detail[:200]}")
        return
    except Exception as exc:
        await update.message.reply_text(f"No se pudo consultar agentes: {exc}")
        return

    items = data.get("items") or []
    if not items:
        await update.message.reply_text("No hay agentes disponibles.")
        return

    lines = ["Agentes disponibles:"]
    for item in items:
        agent_id = item.get("agent_id", "-")
        model = item.get("model", "-")
        last = (item.get("last_message") or {}).get("content") or "sin mensajes"
        preview = last if len(last) <= 80 else f"{last[:77]}..."
        lines.append(f"- {agent_id} ({model}) · {preview}")

    await update.message.reply_text("\n".join(lines))


async def chat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Uso: /chat <agent_id> <mensaje>")
        return

    agent_id = args[0].strip()
    message = " ".join(args[1:]).strip()
    if not agent_id or not message:
        await update.message.reply_text("Uso: /chat <agent_id> <mensaje>")
        return

    payload = {"agent_id": agent_id, "message": message, "source": "telegram"}
    try:
        data = await asyncio.to_thread(
            _http_post_json,
            f"{RUNTIME_BASE_URL}/runtime/chat",
            payload,
        )
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        await update.message.reply_text(f"Error del runtime: HTTP {exc.code} {detail[:400]}")
        return
    except Exception as exc:
        await update.message.reply_text(f"No se pudo enviar mensaje: {exc}")
        return

    response_text = data.get("response") or "Sin respuesta del agente."
    await update.message.reply_text(response_text)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no configurado")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("agents", agents_cmd))
    app.add_handler(CommandHandler("chat", chat_cmd))

    logger.info("Iniciando Telegram bot hacia runtime=%s", urllib_parse.urlparse(RUNTIME_BASE_URL).geturl())
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
