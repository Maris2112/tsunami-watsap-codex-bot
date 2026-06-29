from flask import Flask, request, jsonify
import requests
import traceback
import os
import re
import random
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

import db
import translations as i18n

load_dotenv()

SYSTEM_PROMPT_PATH = os.environ.get("SYSTEM_PROMPT_PATH", "system_prompt.txt")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
BOT_CHAT_ID = os.environ.get("BOT_CHAT_ID")                 # e.g. 77775885000@c.us
INSTANCE = os.getenv("GREENAPI_INSTANCE_ID")
TOKEN = os.getenv("GREENAPI_TOKEN")
GREEN_HOST = "https://7105.api.greenapi.com"

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "77777195000")
INSTAGRAM_URL = "https://www.instagram.com/tsunami_almaty"
GMAPS_URL = "https://www.google.com/maps/search/?api=1&query=43.1624331,76.8991943"
GIS_URL = "https://go.2gis.com/Jbq8h"
BOT_USERNAME = os.getenv("BOT_USERNAME", "tsunamiAIBot")    # Telegram bot for prize redemption

with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

db.init_db()
app = Flask(__name__)
ALMATY = pytz.timezone("Asia/Almaty")

conversation_memory = {}
processed_ids = set()
user_lang = {}
seen = set()                # chat_ids we've already greeted (show menu on first contact)

MENU_WORDS = ("меню", "menu", "мәзір", "0", "/start", "start", "старт")
GREET_WORDS = ("привет", "приветик", "здравствуй", "здравствуйте", "добрый", "доброе",
               "хай", "ассалам", "ассалаумағалейкум", "салам", "салем", "сәлем",
               "сәлеметсіз", "сәлеметсіңіз", "hi", "hello", "hey", "start", "начать")
CANCEL_WORDS = ("отмена", "cancel", "стоп", "болдырмау", "тоқта")
MENU_ACTIONS = {"1": "prices", "2": "hours", "3": "location", "4": "bar",
                "5": "booking", "6": "admin"}


# ===================== Helpers =====================
def db_id(chat_id):
    digits = re.sub(r"\D", "", str(chat_id).split("@")[0])
    return int(digits) if digits else 0


def wa_format(s):
    """Convert the HTML-ish shared strings to WhatsApp-friendly text."""
    s = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2: \1", s)
    s = s.replace("<b>", "*").replace("</b>", "*")
    s = s.replace("<code>", "").replace("</code>", "")
    return s


def ga_send(chat_id, text):
    try:
        if not (INSTANCE and TOKEN):
            print("[ERROR] Green API creds missing"); return
        url = f"{GREEN_HOST}/waInstance{INSTANCE}/sendMessage/{TOKEN}"
        requests.post(url, json={"chatId": chat_id, "message": wa_format(text)}, timeout=20)
    except Exception:
        print("[ERROR] ga_send failed:"); traceback.print_exc()


def ga_send_file(chat_id, url_file, caption=""):
    try:
        if not (INSTANCE and TOKEN):
            print("[ERROR] Green API creds missing"); return
        url = f"{GREEN_HOST}/waInstance{INSTANCE}/sendFileByUrl/{TOKEN}"
        requests.post(url, json={"chatId": chat_id, "urlFile": url_file,
                                 "fileName": "prize.png", "caption": wa_format(caption)}, timeout=25)
    except Exception:
        print("[ERROR] ga_send_file failed:"); traceback.print_exc()


# ===================== Language =====================
def update_lang(chat_id, text=None):
    did = db_id(chat_id)
    if chat_id not in user_lang:
        user_lang[chat_id] = db.get_user_lang(did) or "ru"
    if text:
        low = text.strip().lower()
        if not low.startswith("/") and low not in MENU_WORDS:
            d = i18n.detect_lang(text)
            if d and d != user_lang.get(chat_id):
                user_lang[chat_id] = d
                db.set_user_lang(did, d)
    return user_lang[chat_id]


def L(chat_id):
    if chat_id not in user_lang:
        user_lang[chat_id] = db.get_user_lang(db_id(chat_id)) or "ru"
    return user_lang[chat_id]


# ===================== OpenRouter =====================
def ask_openrouter(question, history=[]):
    try:
        now = datetime.now(ALMATY).strftime("%A, %d %B %Y, %H:%M")
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json",
                   "HTTP-Referer": "https://tsunami-whatsapp-bot-production.up.railway.app",
                   "X-Title": "Tsunami WhatsApp Bot"}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                    {"role": "user", "content": f"[{now}] {question}"}]
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers=headers, json={"model": OPENROUTER_MODEL, "messages": messages}, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("[ERROR] OpenRouter failed:", e); traceback.print_exc()
        return "⚠️ Ошибка ИИ. Попробуй позже."


# ===================== Menu / actions =====================
def send_menu(chat_id):
    ga_send(chat_id, i18n.t(L(chat_id), "wa_menu"))


def menu_action(chat_id, key):
    lang = L(chat_id)
    if key == "prices":
        ga_send(chat_id, i18n.t(lang, "prices"))
    elif key == "hours":
        ga_send(chat_id, i18n.t(lang, "hours"))
    elif key == "location":
        ga_send(chat_id, i18n.t(lang, "loc", g=GMAPS_URL, d=GIS_URL))
    elif key == "bar":
        ga_send(chat_id, f"🍸 {INSTAGRAM_URL}")
    elif key == "admin":
        ga_send(chat_id, f"📞 +7 777 719 5000\nhttps://wa.me/{ADMIN_PHONE}")
    elif key == "booking":
        ga_send(chat_id, i18n.t(lang, "book_call"))


# ===================== Webhook =====================
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    try:
        data = request.get_json(force=True)
        print("[WA WEBHOOK]", data)

        if data.get("typeWebhook") and data.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"status": "ignored"}), 200

        message_id = data.get("idMessage") or data.get("body", {}).get("idMessage")
        if message_id in processed_ids:
            return jsonify({"status": "duplicate"}), 200
        processed_ids.add(message_id)

        msg_data = data.get("body", {}).get("messageData", {}) or data.get("messageData", {})
        text = None
        if "textMessageData" in msg_data:
            text = msg_data["textMessageData"].get("textMessage")
        elif "extendedTextMessageData" in msg_data:
            text = msg_data["extendedTextMessageData"].get("text")

        sender_id = data.get("senderData", {}).get("chatId")
        if not text or not sender_id:
            return jsonify({"status": "no-message"}), 200
        if sender_id == BOT_CHAT_ID:
            return jsonify({"status": "self"}), 200

        update_lang(sender_id, text)
        body = text.strip()
        low = body.lower()

        # menu by default: on first contact, on greetings, or when explicitly asked
        first_contact = sender_id not in seen
        seen.add(sender_id)
        words = re.sub(r"[^\w\s]", " ", low).split()
        is_greet = bool(words) and words[0] in GREET_WORDS

        if low in MENU_WORDS:                      # explicit "меню" shows the menu
            send_menu(sender_id)
            return jsonify({"status": "ok"}), 200
        if first_contact or is_greet:
            send_menu(sender_id)
            return jsonify({"status": "ok"}), 200

        if body in MENU_ACTIONS:
            menu_action(sender_id, MENU_ACTIONS[body])
            return jsonify({"status": "ok"}), 200

        # free text -> AI
        history = conversation_memory.get(sender_id, [])[-6:]
        reply = ask_openrouter(text, history)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        conversation_memory[sender_id] = history
        ga_send(sender_id, reply)
        return jsonify({"status": "ok"}), 200

    except Exception:
        traceback.print_exc()
        return jsonify({"status": "fail"}), 500


@app.route("/", methods=["GET"])
def root():
    return "TsunamiBot для WhatsApp + OpenRouter запущен ✅"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
