# Tsunami WhatsApp Bot 🌊

AI-ассистент летнего бассейна **Tsunami** (Алматы) для **WhatsApp** через **Green API**.
Текстовый аналог Telegram-бота: меню цифрами, бронь, колесо фортуны с QR — на **общей базе** с Telegram.

Прод: `https://tsunami-whatsapp-bot-production.up.railway.app` · бот **+7 777 588 5000**

---

## Почему текстом, а не кнопками
WhatsApp (Green API) не имеет надёжных интерактивных кнопок — Meta отключила их в 2023.
Поэтому меню/бронь/колесо реализованы **текстом** (выбор цифрой), что работает у 100% пользователей.

## Возможности
- **📋 Меню по умолчанию** — приходит само при первом обращении и на приветствие (привет/сәлем/hi…); либо по слову «меню». Пункты 1–7: Цены · Часы · Как добраться · Бар · Бронь · 🎡 Колесо · Админ.
- **🌐 Мультиязык** RU/KZ/EN — по языку сообщения, язык хранится в общей БД (`user_prefs`).
- **🛏 Бронь** — пошагово текстом → запись в общую `contacts` (source `booking_whatsapp`) + заявка на WhatsApp админа.
- **🎡 Колесо фортуны** — общий лимит 1/день с Telegram; приз → **QR-картинка** (Green API `sendFileByUrl`) + код.
- **🎫 Гашение — единое с Telegram:** QR ведёт в Telegram-бота, кассир/вход гасит там же. Приз, выигранный в WhatsApp, гасится тем же сканером.
- **🤖 Свободный вопрос** → OpenRouter (`system_prompt.txt`, идентичен Telegram-версии).

## Архитектура
```
WhatsApp → Green API → POST /webhook (Flask) → роутер:
  первый контакт / приветствие / "меню"  → текстовое меню
  цифра 1–7                               → раздел (цены/часы/гео/бар/бронь/колесо/админ)
  "колесо"                                → спин → QR-картинка + код
  активная бронь                          → текстовый мастер
  свободный текст                         → OpenRouter
```
Общие `db.py` и `translations.py` с Telegram-ботом; обе службы смотрят в один Postgres (`DATABASE_URL`).
WhatsApp `chatId` (`77001234567@c.us`) маппится в БД как число (цифры номера).

## Переменные окружения
| Переменная | Назначение |
|---|---|
| `GREENAPI_INSTANCE_ID` | ID инстанса Green API |
| `GREENAPI_TOKEN` | токен инстанса (секрет) |
| `OPENROUTER_API_KEY` | ключ OpenRouter (секрет) |
| `OPENROUTER_MODEL` | по умолчанию `google/gemini-2.5-flash-lite` |
| `BOT_CHAT_ID` | номер бота `77775885000@c.us` (защита от само-ответов) |
| `DATABASE_URL` | общий Postgres (ссылка `${{Postgres.DATABASE_URL}}`) |
| `ADMIN_PHONE` | WhatsApp админа для заявок (по умолч. 77777195000) |
| `BOT_USERNAME` | Telegram-бот для гашения QR (по умолч. tsunamiAIBot) |

## Настройка Green API
В кабинете инстанса → webhookUrl = `https://<домен>/webhook`, включить **«Входящие сообщения и файлы»**.

## Запуск / деплой
```bash
pip install -r requirements.txt
python main.py            # PORT 8080, эндпоинт /webhook
```
Railway (Hobby), `Procfile`: `web: python main.py`, деплой `railway up`. Общий Postgres-сервис проекта.

> ⚠️ Секреты не коммитятся (`.env` в `.gitignore`).
