from dotenv import load_dotenv
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in .env or environment")

PAYMENT_URL_1 = os.getenv("PAYMENT_URL_1", "https://example.com/pay1")
PAYMENT_URL_2 = os.getenv("PAYMENT_URL_2", "https://example.com/pay2")
CRYPTO_ADDRESS = os.getenv("CRYPTO_ADDRESS", "TRXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
CRYPTO_NETWORK = os.getenv("CRYPTO_NETWORK", "TRC20")

async def send_welcome_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "� The Bundler\n\n"
        "Entry to the Suite is limited to approved members.\n\n"
        "Unlock premium utilities, private channels, and exclusive resources with a one-time €100 access pass.\n\n"
        "Choose your gateway below and begin your journey."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Apple Pay", callback_data="pay_apple"), InlineKeyboardButton("Crypto", callback_data="pay_crypto")]
    ])

    await update.message.reply_text(text, reply_markup=keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome_payment(update, context)


def get_group_chat_id_candidates(group_id: str):
    candidates = []
    normalized = group_id.strip()

    if normalized.startswith("-") and normalized[1:].isdigit():
        candidates.append(int(normalized))
    elif normalized.isdigit():
        candidates.append(int(normalized))
        candidates.append(int(f"-100{normalized}"))
    return candidates

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if query.data == "pay_crypto":
        await query.message.reply_text(
            f"Send exactly $100 USDT to the following address on {CRYPTO_NETWORK}:\n\n"
            f"`{CRYPTO_ADDRESS}`\n\n"
            "Once payment is made, send a screenshot or message here and an admin will verify it manually."
        )
        return
    await query.message.reply_text("Payment verified! Constructing your single-use invite link..")

    group_id = os.getenv("GROUP_CHAT_ID")
    if not group_id:
        await query.message.reply_text("GROUP_CHAT_ID is not set in environment. Set it to enable invite link creation.")
        return

    candidates = get_group_chat_id_candidates(group_id)
    if not candidates:
        await query.message.reply_text("GROUP_CHAT_ID is invalid. Use the numeric chat id of your private group.")
        return

    last_error = None
    for chat_id in candidates:
        try:
            invite = await context.bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            await query.message.reply_text(f"Here is your single-use invite link:\n{invite.invite_link}")
            return
        except BadRequest as e:
            last_error = str(e)

    await query.message.reply_text(
        "Failed to create invite link. Please check that the bot is added to the group, "
        "is an admin with invite-link permission, and that GROUP_CHAT_ID is correct. "
        f"Last error: {last_error}"
    )

async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        await update.message.reply_text(f"This group chat id is: {chat.id}")
    else:
        await update.message.reply_text("Use this command inside the group to get the private group id.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("groupid", groupid))
    # only respond to direct/private chats for the payment prompt
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_welcome_payment))
    # handle payment button callbacks
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r"^pay_"))
    app.run_polling()

if __name__ == "__main__":
    main()
