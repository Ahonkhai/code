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

The bot implements `/start` and sends a payment welcome message when a user DMs it.

Payment setup

1. Add payment URLs to your environment file.

```
PAYMENT_URL_1=https://your-apple-pay-link
PAYMENT_URL_2=https://your-crypto-pay-link
```

When a new user messages the bot the first time it will receive a welcome message with payment buttons.
