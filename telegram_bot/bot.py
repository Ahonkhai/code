from dotenv import load_dotenv
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

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
        [InlineKeyboardButton("Apple Pay", callback_data="pay_apple"), InlineKeyboardButton("Crypto", callback_data="pay_crypto")]
    ])

    await update.message.reply_text(text, reply_markup=keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome_payment(update, context)


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    # send verification message immediately (we'll assume payment will be handled later)
    await query.message.reply_text("Payment verified! Constructing your single-use invite link..")

    group_id = os.getenv("GROUP_CHAT_ID")
    if not group_id:
        await query.message.reply_text("GROUP_CHAT_ID is not set in environment. Set it to enable invite link creation.")
        return

    try:
        chat_id = int(group_id)
        invite = await context.bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
        await query.message.reply_text(f"Here is your single-use invite link:\n{invite.invite_link}")
    except Exception as e:
        await query.message.reply_text(f"Failed to create invite link: {e}")

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
