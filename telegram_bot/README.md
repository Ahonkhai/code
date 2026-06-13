# Telegram Bot (Python)

Minimal Telegram bot using `python-telegram-bot` (polling).

Setup

1. Create a bot and get a token from BotFather on Telegram.
2. Create a `.env` file in the `telegram_bot` folder and set `TELEGRAM_TOKEN`.
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

1. Add your payment options and group chat settings to `telegram_bot/.env`:

```dotenv
TELEGRAM_TOKEN=your_bot_token
GROUP_CHAT_ID=-1001234567890
CRYPTO_ADDRESS=0xe793872cF1562D2332350173511c529cAbE1817f
CRYPTO_NETWORK=ERC20
ETHERSCAN_API_KEY=your_etherscan_api_key
USDT_CONTRACT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7
```

2. Restart the bot after updating `.env`.

Verification flow

- Users click `Crypto` and receive the USDT address.
- They then send their transaction hash to the bot with `/verify <txhash>` or by pasting it directly.
- The bot checks the transaction automatically and issues a single-use invite link if the payment is valid.

Make sure the bot is added to the private group and is an admin with invite-link permission.
