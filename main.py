from flask import Flask, request
import requests, os, json
from dotenv import load_dotenv

load_dotenv()

GREENAPI_INSTANCE_ID = os.environ["GREENAPI_INSTANCE_ID"]
GREENAPI_TOKEN = os.environ["GREENAPI_TOKEN"]
GREENAPI_API_URL = os.environ["GREENAPI_API_URL"]
GREENAPI_MEDIA_URL = os.environ["GREENAPI_MEDIA_URL"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", "system_prompt.txt")
with open(prompt_path, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "TsunamiBot is running ✅"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    message_data = data.get("messageData", {})
    if message_data.get("typeMessage") != "textMessage":
        return "Ignored", 200
    user_msg = message_data.get("textMessageData", {}).get("textMessage", "")

    reply = call_openrouter(user_msg)

    chat_id = data.get("senderData", {}).get("chatId")
    send_message(chat_id, reply)
    return "OK", 200

def call_openrouter(user_msg):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "meta-llama/llama-3-70b-instruct",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    return r.json()["choices"][0]["message"]["content"]

def send_message(chat_id, text):
    url = f"{GREENAPI_API_URL}/waInstance{GREENAPI_INSTANCE_ID}/sendMessage/{GREENAPI_TOKEN}"
    payload = {"chatId": chat_id, "message": text}
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(port=5000)
