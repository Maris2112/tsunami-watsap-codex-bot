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
booking_state = {}
user_lang = {}
seen = set()                # chat_ids we've already greeted (show menu on first contact)

MENU_WORDS = ("меню", "menu", "мәзір", "0", "/start", "start", "старт")
GREET_WORDS = ("привет", "приветик", "здравствуй", "здравствуйте", "добрый", "доброе",
               "хай", "ассалам", "ассалаумағалейкум", "салам", "салем", "сәлем",
               "сәлеметсіз", "сәлеметсіңіз", "hi", "hello", "hey", "start", "начать")
CANCEL_WORDS = ("отмена", "cancel", "стоп", "болдырмау", "тоқта")
WHEEL_WORDS = ("колесо", "wheel", "колесо фортуны", "сәттілік дөңгелегі", "fortune")
MENU_ACTIONS = {"1": "prices", "2": "hours", "3": "location", "4": "bar",
                "5": "booking", "6": "wheel", "7": "admin"}


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
        start_booking(chat_id)
    elif key == "wheel":
        do_spin(chat_id)


# ===================== Wheel =====================
def do_spin(chat_id):
    lang = L(chat_id)
    did = db_id(chat_id)
    if not db.can_spin_today(did):
        ga_send(chat_id, i18n.t(lang, "w_already")); return
    idx = random.choices(range(len(i18n.PRIZES)), weights=[p["w"] for p in i18n.PRIZES], k=1)[0]
    p = i18n.PRIZES[idx]
    db.record_spin(did, p["key"])
    label = p.get(lang) or p["ru"]
    if not p["real"]:
        ga_send(chat_id, i18n.t(lang, "w_lose", prize=label)); return
    code = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=6))
    today = datetime.now(ALMATY).date()
    db.create_prize(code, did, p["key"], p["ru"], p["role"], today)
    deeplink = f"https://t.me/{BOT_USERNAME}?start=rdm_{code}"
    qr = "https://api.qrserver.com/v1/create-qr-code/?size=320x320&margin=12&data=" + requests.utils.quote(deeplink, safe="")
    who = i18n.t(lang, "redeem_cashier" if p["role"] == "cashier" else "redeem_entrance")
    ga_send_file(chat_id, qr, i18n.t(lang, "w_win_qr", prize=label, who=who, code=code))


# ===================== Booking (text wizard) =====================
def start_booking(chat_id):
    booking_state[chat_id] = {"step": "date", "data": {}}
    ga_send(chat_id, i18n.t(L(chat_id), "bk1") + "\n(сегодня / завтра / 25.06)")


def _norm_zone(t):
    t = t.lower()
    if "vip" in t and ("2" in t or "ii" in t):
        return "VIP 2"
    if "vip" in t and ("1" in t or "i" in t):
        return "VIP 1"
    return "Standard"


def booking_finish(chat_id):
    lang = L(chat_id)
    T = i18n.t
    d = booking_state[chat_id]["data"]
    summary = (f"{T(lang,'sum_date')}: {d.get('date','—')}\n"
               f"{T(lang,'sum_zone')}: {d.get('zone','—')}\n"
               f"{T(lang,'sum_people')}: {d.get('people','—')}\n"
               f"{T(lang,'sum_name')}: {d.get('name','—')}\n"
               f"{T(lang,'sum_phone')}: {d.get('phone','—')}")
    done = {"ru": "✅ Заявка принята! Администратор свяжется с тобой 👍",
            "kk": "✅ Өтінім қабылданды! Әкімші сізбен хабарласады 👍",
            "en": "✅ Request received! The administrator will contact you 👍"}[lang]
    ga_send(chat_id, done + "\n\n" + summary)
    db.save_contact(db_id(chat_id), d.get("name"), d.get("phone"), source="booking_whatsapp",
                    extra=f"date={d.get('date')}; zone={d.get('zone')}; people={d.get('people')}; wa={chat_id}")
    ga_send(f"{ADMIN_PHONE}@c.us", "🆕 Новая бронь из WhatsApp-бота:\n" + summary + f"\nWhatsApp: {chat_id}")
    booking_state.pop(chat_id, None)


def handle_booking_text(chat_id, text):
    lang = L(chat_id)
    if text.strip().lower() in CANCEL_WORDS:
        booking_state.pop(chat_id, None)
        ga_send(chat_id, i18n.t(lang, "bk_cancelled")); return
    st = booking_state[chat_id]
    step = st["step"]
    low = text.strip().lower()
    if step == "date":
        today = datetime.now(ALMATY)
        if low in ("сегодня", "today", "бүгін"):
            st["data"]["date"] = today.strftime("%d.%m.%Y")
        elif low in ("завтра", "tomorrow", "ертең"):
            st["data"]["date"] = (today + timedelta(days=1)).strftime("%d.%m.%Y")
        else:
            st["data"]["date"] = text.strip()
        st["step"] = "zone"
        ga_send(chat_id, i18n.t(lang, "bk2") + "\n(Standard / VIP1 / VIP2)")
    elif step == "zone":
        st["data"]["zone"] = _norm_zone(text)
        st["step"] = "people"
        ga_send(chat_id, i18n.t(lang, "bk3"))
    elif step == "people":
        st["data"]["people"] = text.strip()
        st["step"] = "name"
        ga_send(chat_id, i18n.t(lang, "bk4"))
    elif step == "name":
        st["data"]["name"] = text.strip()
        st["step"] = "phone"
        ga_send(chat_id, i18n.t(lang, "bk5"))
    elif step == "phone":
        st["data"]["phone"] = text.strip()
        booking_finish(chat_id)


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

        if low in MENU_WORDS:                      # explicit "меню" always escapes booking
            booking_state.pop(sender_id, None)
            send_menu(sender_id)
            return jsonify({"status": "ok"}), 200
        if (first_contact or is_greet) and sender_id not in booking_state:
            send_menu(sender_id)
            return jsonify({"status": "ok"}), 200

        if sender_id in booking_state:
            handle_booking_text(sender_id, body)
            return jsonify({"status": "ok"}), 200

        if low in WHEEL_WORDS:
            do_spin(sender_id)
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
