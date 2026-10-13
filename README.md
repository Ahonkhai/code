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

---

# Launch & trading bot (`trader/`)

A Solana / pump.fun bot with a button menu: **🚀 Launch · 🔑 Wallets · 📁 Portfolio · 🧾 Tx tracker · 🛡 Settings**.

- **Launch**: step-by-step token creation (name 1-32, symbol 2-10 A-Z, description, square PNG/JPG image, a trade size of 5/10/15/25 SOL bought at launch by the creator's wallet, then optional X / Telegram / Website / Instagram links), with "Latest" and "Hot" tokens shown as inspiration on the name step.
- **Wallets**: create / import / export / withdraw / remove. Secret keys are encrypted with `WALLET_ENCRYPTION_KEY` before being saved, and imported key messages are deleted from the chat.
- **Trading**: paste any token address for a token card with price, market cap, safety checks (mint/freeze authority, top holders), and Buy / Sell buttons.
- **Portfolio**: SOL and token balances across all wallets with USD values (Jupiter prices).
- **Tx tracker**: every transaction is watched and you get a ✅ / ❌ / ⌛ message when it lands, fails or is dropped.
- **Sniper protection**: per-user max slippage (trades fail rather than get sniped or sandwiched) and priority fee.

Transactions are built by [PumpPortal's local API](https://pumpportal.fun/local-trading-api/trading-api) and signed inside the bot, so keys never leave it. PumpPortal charges a small fee per trade; check their current pricing.

## Run

```bash
pip install -r requirements.txt
# add the variables from .env.example to .env
python -m trader
```

Docker: same image, with `CMD ["python", "-m", "trader"]`.

## Notes

- `trader.db` holds the encrypted wallets. Back up both it **and** `WALLET_ENCRYPTION_KEY`; losing either loses access to the wallets.
- The Latest/Hot feed uses pump.fun's unofficial frontend API (`PUMP_COINS_URL`), which can change without notice.
- Tests: `python -m pytest tests/test_trader.py` (fully offline; RPC and APIs are mocked).
