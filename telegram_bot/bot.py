from dotenv import load_dotenv
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in .env or environment")

PAYMENT_URL_1 = os.getenv("PAYMENT_URL_1", "https://example.com/pay1")
PAYMENT_URL_2 = os.getenv("PAYMENT_URL_2", "https://example.com/pay2")

async def send_welcome_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Welcome to the Premium Suite!\n\n"
        "To engage with the community and unlock access to the Bundler utilities, a €100 entry fee is required. "
        "Please choose your payment gateway below:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Apple Pay", url=PAYMENT_URL_1), InlineKeyboardButton("Crypto", url=PAYMENT_URL_2)]
    ])

    await update.message.reply_text(text, reply_markup=keyboard)

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
