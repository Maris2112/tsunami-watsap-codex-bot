from flask import Flask, request, jsonify
import requests
import traceback
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv

# === Загрузка переменных окружения ===
load_dotenv()

# === Константы ===
SYSTEM_PROMPT_PATH = os.environ.get("SYSTEM_PROMPT_PATH", "system_prompt.txt")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
BOT_CHAT_ID = os.environ.get("BOT_CHAT_ID")  # Пример: "7775885000@c.us"
WHATSAPP_INSTANCE_ID = os.getenv("WHATSAPP_INSTANCE_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# === Загрузка системного промпта ===
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# === Flask-приложение ===
app = Flask(__name__)

# === Память и кэш ===
conversation_memory = {}
processed_whatsapp_ids = set()

# === Отправка сообщения через Green API ===
def send_whatsapp_message(chat_id, message):
    try:
        url = f"https://7105.api.greenapi.com/waInstance{WHATSAPP_INSTANCE_ID}/sendMessage/{WHATSAPP_TOKEN}"
        payload = {
            "chatId": chat_id,
            "message": message
        }
        response = requests.post(url, json=payload)
        print("[SEND]", response.status_code, response.text)
    except Exception:
        print("[ERROR] WhatsApp message failed:")
        traceback.print_exc()

# === Вызов OpenRouter ===
def ask_openrouter(question, history=[]):
    try:
        tz = pytz.timezone("Asia/Almaty")
        now = datetime.now(tz).strftime("%A, %d %B %Y, %H:%M")
        full_question = f"[{now}] {question}"

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tsunami-whatsapp.up.railway.app",
            "X-Title": "Tsunami WhatsApp Bot"
        }

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": full_question},
        ]

        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload
        )

        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    except Exception as e:
        print("[ERROR] OpenRouter call failed:", e)
        traceback.print_exc()
        return "⚠️ Ошибка ИИ. Попробуй позже."

# === Webhook для входящих WhatsApp-сообщений ===
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    try:
        data = request.get_json(force=True)
        print("[WA WEBHOOK]", data)

        # ✅ Фильтр по типу хука
        type_hook = data.get("typeWebhook")
        if type_hook and type_hook != "incomingMessageReceived":
            print(f"[SKIP] Неподходящий тип хука: {type_hook}")
            return jsonify({"status": "ignored"}), 200

        # ✅ Проверка ID на повтор
        message_id = data.get("idMessage") or data.get("body", {}).get("idMessage")
        if message_id in processed_whatsapp_ids:
            print(f"[DUPLICATE] Уже обработано: {message_id}")
            return jsonify({"status": "duplicate"}), 200
        processed_whatsapp_ids.add(message_id)

        # ✅ Извлечение текста
        msg_data = (
            data.get("body", {}).get("messageData", {}) or
            data.get("messageData", {})
        )

        text = None
        if "textMessageData" in msg_data:
            text = msg_data["textMessageData"].get("textMessage")
        elif "extendedTextMessageData" in msg_data:
            text = msg_data["extendedTextMessageData"].get("text")

        sender_id = data.get("senderData", {}).get("chatId")

        if not text or not sender_id:
            print("[SKIP] Пустое сообщение от WhatsApp")
            return jsonify({"status": "no-message"}), 200

        if sender_id == BOT_CHAT_ID:
            print("[SKIP] Сам себе отправил сообщение.")
            return jsonify({"status": "self-message"}), 200

        # ✅ Вызов OpenRouter
        history = conversation_memory.get(sender_id, [])[-6:]
        reply = ask_openrouter(text, history)

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        conversation_memory[sender_id] = history

        # ✅ Отправка ответа в WhatsApp
        send_whatsapp_message(sender_id, reply)

        return jsonify({"status": "ok"}), 200

    except Exception:
        traceback.print_exc()
        return jsonify({"status": "fail"}), 500

# === Проверка доступности ===
@app.route("/", methods=["GET"])
def root():
    return "TsunamiBot для WhatsApp + OpenRouter запущен ✅"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


