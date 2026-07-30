import os
import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

app = FastAPI()

BOT_TOKEN = os.environ["BOT_TOKEN"]
LOG_FILE = "run.jsonl"

application = Application.builder().token(BOT_TOKEN).build()

_initialized = False


async def ensure_initialized():
    global _initialized

    if not _initialized:
        await application.initialize()
        _initialized = True


def write_log(question, answer):
    record = {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "answer": answer
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return

    question = update.message.text

    answer = {
        "message": "Agent received the question",
        "question": question
    }

    write_log(question, answer)

    response = {
        "answer": answer,
        "log_url": "https://telegram-data-analyst-bot-62fo.onrender.com/run.jsonl"
    }

    await update.message.reply_text(
        json.dumps(response, ensure_ascii=False)
    )


application.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)


@app.get("/")
async def health():
    return {"status": "ok"}


@app.get("/run.jsonl", response_class=PlainTextResponse)
async def logs():
    if not os.path.exists(LOG_FILE):
        return ""

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/telegram")
async def telegram_endpoint(request: Request):
    await ensure_initialized()

    data = await request.json()

    update = Update.de_json(data, application.bot)

    await application.process_update(update)

    return {"ok": True}
