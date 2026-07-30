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
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

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


async def ask_gemini(question):
    prompt = """
You are a careful data-analysis agent.

Solve the user's question accurately.

Rules:
1. Return ONLY valid JSON.
2. Do not use markdown.
3. Do not add explanations outside JSON.
4. Follow the exact answer structure requested by the user.
5. If the user asks for a particular JSON structure, follow it exactly.
6. If data is provided inline, calculate from that data.
7. Do not invent facts or numbers.
8. Perform calculations carefully.
9. For multi-turn conversations, answer the latest question using relevant earlier context.
10. Return a JSON value that can be placed directly inside the outer "answer" field.

User question:
""" + question

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json"
        }
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()

        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return

    question = update.message.text

    try:
        raw_answer = await ask_gemini(question)

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
