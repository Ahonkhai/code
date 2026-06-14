from dotenv import load_dotenv
import asyncio
import os
import json
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN in .env or environment")

PAYMENT_URL_1 = os.getenv("PAYMENT_URL_1", "https://example.com/pay1")
PAYMENT_URL_2 = os.getenv("PAYMENT_URL_2", "https://example.com/pay2")
CRYPTO_ADDRESS = os.getenv("CRYPTO_ADDRESS", "0xe793872cF1562D2332350173511c529cAbE1817f")
CRYPTO_NETWORK = os.getenv("CRYPTO_NETWORK", "ERC20")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "SWANH4QEPE5SABEA97HZG126ZJYWRCUBTE")
VERIFIED_USERS_FILE = os.path.join(os.path.dirname(__file__), "verified_users.json")
USDT_DECIMALS = 6
USDT_REQUIRED_AMOUNT = 100
USDT_CONTRACT_ADDRESS = os.getenv("USDT_CONTRACT_ADDRESS", "0xdAC17F958D2ee523a2206206994597C13D831ec7")

def load_verified_users():
    try:
        with open(VERIFIED_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_verified_users(data):
    with open(VERIFIED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def is_verified_user(user_id: int):
    users = load_verified_users()
    return str(user_id) in users


def add_verified_user(user_id: int, tx_hash: str):
    users = load_verified_users()
    users[str(user_id)] = {"tx_hash": tx_hash}
    save_verified_users(users)


async def send_welcome_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id and is_verified_user(user_id):
        await update.message.reply_text("You are already verified. If you need help, send /help.")
        return

    text = (
        "🜂 The Bundler\n\n"
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
        if not CRYPTO_ADDRESS:
            await query.message.reply_text(
                "Crypto payment address is not configured. "
                "Set CRYPTO_ADDRESS in your .env file and restart the bot."
            )
            return

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Verify", callback_data="pay_verify")]
        ])

        await query.message.reply_text(
            f"Send exactly $100 USDT to the following address on {CRYPTO_NETWORK}:\n\n"
            f"`{CRYPTO_ADDRESS}`\n\n"
            "When the transfer is complete, click Verify and send your transaction hash.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return

    if query.data == "pay_verify":
        await query.message.reply_text(
            "Please send your transaction hash in this chat. "
            "If the hash is incorrect, you will receive a failed transaction response."
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

def verify_usdt_transaction(tx_hash: str):
    if not ETHERSCAN_API_KEY:
        return False, "ETHERSCAN_API_KEY is not set in .env."

    response = requests.get(
        "https://api.etherscan.io/api",
        params={
            "module": "account",
            "action": "tokentx",
            "contractaddress": USDT_CONTRACT_ADDRESS,
            "address": CRYPTO_ADDRESS,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "desc",
            "apikey": ETHERSCAN_API_KEY,
        },
        timeout=20,
    )
    data = response.json()
    if data.get("status") != "1":
        return False, data.get("message", "Unable to query Etherscan")

    for tx in data.get("result", []):
        if tx.get("hash", "").lower() == tx_hash.lower():
            if tx.get("to", "").lower() != CRYPTO_ADDRESS.lower():
                return False, "Transaction was not sent to the configured USDT address."
            amount = int(tx.get("value", "0"))
            required_amount = USDT_REQUIRED_AMOUNT * 10 ** USDT_DECIMALS
            if amount != required_amount:
                return False, f"Transaction amount is not exactly {USDT_REQUIRED_AMOUNT} USDT."
            return True, "Verified"

    return False, "No matching USDT transaction found for that hash." 


async def verify_crypto_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    if message.startswith("/verify"):
        parts = message.split()
        if len(parts) < 2:
            await update.message.reply_text("Usage: /verify <txhash>")
            return
        tx_hash = parts[1]
    else:
        tx_hash = message

    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        await update.message.reply_text("Please send a valid transaction hash starting with 0x.")
        return

    success, details = verify_usdt_transaction(tx_hash)
    if not success:
        await update.message.reply_text(f"Verification failed for tx {tx_hash}: {details}")
        # {details} can contain sensitive info, so we won't include it in the user-facing message, but we will log it
        return

    user_id = update.effective_user.id if update.effective_user else None
    if user_id and is_verified_user(user_id):
        await update.message.reply_text("You are already verified.")
        return

    group_id = os.getenv("GROUP_CHAT_ID")
    if not group_id:
        await update.message.reply_text("GROUP_CHAT_ID is not set in environment. Set it to enable invite link creation.")
        return

    candidates = get_group_chat_id_candidates(group_id)
    if not candidates:
        await update.message.reply_text("GROUP_CHAT_ID is invalid. Use the numeric chat id of your private group.")
        return

    last_error = None
    for chat_id in candidates:
        try:
            invite = await context.bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            if user_id:
                add_verified_user(user_id, tx_hash)
            await update.message.reply_text("Payment verified! Constructing your single-use invite link..")
            await update.message.reply_text(f"Here is your single-use invite link:\n{invite.invite_link}")
            return
        except BadRequest as e:
            last_error = str(e)

    await update.message.reply_text(
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
    print(f"Loaded CRYPTO_ADDRESS={CRYPTO_ADDRESS} CRYPTO_NETWORK={CRYPTO_NETWORK}")
    if not CRYPTO_ADDRESS:
        print("WARNING: CRYPTO_ADDRESS is not set. Update .env and restart the bot.")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("groupid", groupid))
    app.add_handler(CommandHandler("verify", verify_crypto_tx))
    app.add_handler(MessageHandler(filters.Regex(r"^0x[a-fA-F0-9]{64}$") & filters.ChatType.PRIVATE, verify_crypto_tx))
    # only respond to direct/private chats for the payment prompt
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_welcome_payment))
    # handle payment button callbacks
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r"^pay_"))
    app.run_polling()

if __name__ == "__main__":
    main()
