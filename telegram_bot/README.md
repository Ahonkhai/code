# Telegram Bot (Python)

Minimal Telegram bot using `python-telegram-bot` (polling).

Setup

1. Create a bot and get a token from BotFather on Telegram.
2. Copy `.env.example` to `.env` and set `TELEGRAM_TOKEN`.
3. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Run

```bash
python bot.py
```

The bot implements `/start` and echoes any text message.
