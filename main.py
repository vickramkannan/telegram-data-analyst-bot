import os
import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

app = FastAPI()

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

LOG_FILE = "run.jsonl"
LOG_URL = "https://telegram-data-analyst-bot-62fo.onrender.com/run.jsonl"

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


async def ask_openai(question):
    system_prompt = """
You are a careful data-analysis agent.

The user will give you a data-analysis question.

Your job is to solve the question as accurately as possible.

Important rules:
1. Return ONLY valid JSON.
2. Do not use markdown.
3. Do not add explanations outside the JSON.
4. Follow the exact answer structure requested by the user.
5. If the user explicitly asks for a JSON shape, use that exact shape inside "answer".
6. Do not invent data.
7. If the question contains data inline, calculate from that data.
8. If the question provides a public dataset URL, retrieve and analyze it when possible.
9. For calculations, actually calculate rather than guessing.
10. Preserve numbers accurately.
"""

    payload = {
        "model": "gpt-5-mini",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": question
            }
        ],
        "temperature": 0
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload
        )

        response.raise_for_status()

        data = response.json()

        content = data["choices"][0]["message"]["content"].strip()

        return content


async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return

    question = update.message.text

    try:
        raw_answer = await ask_openai(question)

        # Remove accidental markdown code fences.
        if raw_answer.startswith("```"):
            raw_answer = raw_answer.replace("```json", "", 1)
            raw_answer = raw_answer.replace("```", "")
            raw_answer = raw_answer.strip()

        answer = json.loads(raw_answer)

    except Exception as e:
        answer = {
            "error": str(e)
        }

    write_log(question, answer)

    final_response = {
        "answer": answer,
        "log_url": LOG_URL
    }

    # Telegram receives exactly the JSON object.
    await update.message.reply_text(
        json.dumps(final_response, ensure_ascii=False)
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
