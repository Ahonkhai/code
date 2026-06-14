from dotenv import load_dotenv
import asyncio
import os
import json
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
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

async def grant_group_access(bot, user_id: int, tx_hash: str, reply_func):
    if not user_id:
        await reply_func(
            "Could not determine your Telegram user id. Please restart the bot and try again."
        )
        return False

    group_id = os.getenv("GROUP_CHAT_ID")
    if not group_id:
        await reply_func("GROUP_CHAT_ID is not set in environment. Set it to enable group access.")
        return False

    candidates = get_group_chat_id_candidates(group_id)
    if not candidates:
        await reply_func("GROUP_CHAT_ID is invalid. Use the numeric chat id of your private group.")
        return False

    last_error = None
    for chat_id in candidates:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status not in ("member", "restricted", "administrator", "creator"):
                await reply_func(
                    "Please join the group first before your access can be activated. "
                    "Then verify again."
                )
                return False

            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
            )
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                use_independent_chat_permissions=True,
            )
            add_verified_user(user_id, tx_hash)
            await reply_func(
                "Payment verified! Your access has been activated.\n"
                "You can now send messages in the group."
            )
            return True
        except BadRequest as e:
            last_error = str(e)

    await reply_func(
        "Payment verified, but we could not activate your group access. "
        "Please ensure you have joined the group first and that the bot is admin. "
        f"Last error: {last_error}"
    )
    return False

async def restrict_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        try:
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
            )
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=member.id,
                permissions=permissions,
                use_independent_chat_permissions=True,
            )
            await update.message.reply_text(
                f"Welcome {member.full_name}! You are in spectator mode until payment is verified. "
                # "Send me /start in private chat to begin payment."
            )
        except BadRequest as e:
            print(f"restrict_new_member failed for {member.id} in chat {chat_id}: {e}")
            await update.message.reply_text(
                "Unable to restrict new member automatically. "
                "Make sure the bot is an admin with permission to restrict members."
            )
            continue

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
            "Payment Confirmation Required\n\n"
            "To complete your activation, please submit your transaction hash in this chat.\n\n"
            "Our system will verify the transaction automatically. Only valid, confirmed transaction hashes can be processed successfully."
        )
        return

    user_id = update.effective_user.id if update.effective_user else None
    await grant_group_access(context.bot, user_id, "apple_pay", query.message.reply_text)

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
        await update.message.reply_text(
            "Transaction verification failed:\n"
            f"Transaction hash: `{tx_hash}`\n"
            f"Reason: {details}",
            parse_mode=ParseMode.MARKDOWN,
        )
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

    await grant_group_access(context.bot, user_id, tx_hash, update.message.reply_text)


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
    # automatically restrict new members on join when group default allows sending
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.ChatType.GROUPS, restrict_new_member))
    # only respond to direct/private chats for the payment prompt
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_welcome_payment))
    # handle payment button callbacks
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r"^pay_"))
    app.run_polling()

if __name__ == "__main__":
    main()
