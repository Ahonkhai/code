from dotenv import load_dotenv
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in .env or environment")

PAYMENT_URL_1 = os.getenv("PAYMENT_URL_1", "https://example.com/pay1")
PAYMENT_URL_2 = os.getenv("PAYMENT_URL_2", "https://example.com/pay2")
DATA_FILE = os.path.join(os.path.dirname(__file__), "joined_users.json")

def load_joined():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def add_joined(user_id: str):
    users = load_joined()
    if user_id in users:
        return
    users.append(user_id)
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f)
    except Exception:
        pass

async def send_welcome_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id) if user else None
    joined = load_joined()

    if user_id and user_id in joined:
        await update.message.reply_text("You're already registered. If you need help, send /help")
        return

    text = (
        "👋 Welcome to the Premium Suite!\n\n"
        "To engage with the community and unlock access to the Bundler utilities, a €100 entry fee is required. "
        "Please choose your payment gateway below:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Pay with Stripe", url=PAYMENT_URL_1), InlineKeyboardButton("Pay with PayPal", url=PAYMENT_URL_2)]
    ])

    await update.message.reply_text(text, reply_markup=keyboard)
    if user_id:
        add_joined(user_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome_payment(update, context)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_welcome_payment))
    app.run_polling()

if __name__ == "__main__":
    main()
