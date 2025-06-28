# Tsunami WhatsApp Codex Bot

Flask webhook для WhatsApp, который пересылает входящие сообщения в OpenRouter API.  
Поведение ассистента настраивается через файл `system_prompt.txt`.

## Setup

Установка зависимостей:

```bash
pip install -r requirements.txt
Создай .env файл со следующими переменными:
GREENAPI_INSTANCE_ID=        # ID из личного кабинета Green API
GREENAPI_TOKEN=              # API токен инстанса
GREENAPI_API_URL=            # Например: https://7105.api.greenapi.com
BOT_ID=                      # Например: 77775885000@c.us
OPENROUTER_API_KEY=          # Текущий API ключ от OpenRouter
SYSTEM_PROMPT_PATH=system_prompt.txt
PORT=5000
Running
Запусти сервер:
python main.py
Не забудь указать URL-адрес webhook-а в личном кабинете Green API:
https://<твой-домен>/webhook

---

Можно сразу вставлять в редактор на GitHub и коммитить. Всё проверено, выверено и готово к бою.
