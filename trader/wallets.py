from solders.keypair import Keypair
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import config
from .common import HOME_BTN, back_kb, cancel_kb, esc, reply, set_awaiting, short, svc, tx_link
from .keystore import export_secret_key, parse_secret_key
from .solana_rpc import LAMPORTS_PER_SOL, TX_FEE_LAMPORTS, is_pubkey

EXPORT_TTL_SECONDS = 60


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = svc(context)
    wallets = s.db.list_wallets(update.effective_user.id)
    lines = ["🔑 <b>Wallets</b>\n"]
    rows = []
    for w in wallets:
        try:
            bal = f"{await s.rpc.balance_sol(w.pubkey):.4f} SOL"
        except Exception:
            bal = "balance unavailable"
        star = "⭐ " if w.is_default else ""
        lines.append(f"{star}<b>{esc(w.label)}</b>\n<code>{w.pubkey}</code>\n{bal}\n")
        rows.append([Btn(f"{star}{w.label} ({short(w.pubkey)})", callback_data=f"w:view:{w.id}")])
    if not wallets:
        lines.append("No wallets yet. Create a new one or import an existing wallet.")
    rows.append([Btn("➕ Create", callback_data="w:new"), Btn("📥 Import", callback_data="w:import")])
    await reply(update, "\n".join(lines), back_kb(*rows), edit=True)


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    s = svc(context)
    w = s.db.get_wallet(update.effective_user.id, wallet_id)
    if not w:
        await show_list(update, context)
        return
    try:
        bal = f"{await s.rpc.balance_sol(w.pubkey):.4f} SOL"
    except Exception:
        bal = "balance unavailable"
    text = (
        f"🔑 <b>{esc(w.label)}</b>{' ⭐ default' if w.is_default else ''}\n\n"
        f"Address (tap to copy):\n<code>{w.pubkey}</code>\n\nBalance: {bal}\n\n"
        "Send SOL to this address to fund it."
    )
    rows = [
        [Btn("⭐ Make default", callback_data=f"w:default:{w.id}"), Btn("📤 Withdraw", callback_data=f"w:withdraw:{w.id}")],
        [Btn("🔐 Export key", callback_data=f"w:export:{w.id}"), Btn("🗑 Remove", callback_data=f"w:del:{w.id}")],
        [Btn("⬅️ Wallets", callback_data="w:list")],
    ]
    await reply(update, text, back_kb(*rows), edit=True)


def _check_limit(context, user_id: int) -> bool:
    return len(svc(context).db.list_wallets(user_id)) < config.MAX_WALLETS_PER_USER


async def create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _check_limit(context, user_id):
        await reply(update, f"Wallet limit reached ({config.MAX_WALLETS_PER_USER}).", back_kb())
        return
    s = svc(context)
    kp = Keypair()
    n = len(s.db.list_wallets(user_id)) + 1
    w = s.db.add_wallet(user_id, f"Wallet {n}", str(kp.pubkey()), s.keystore.encrypt(kp))
    await reply(
        update,
        f"✅ Created <b>{esc(w.label)}</b>\n<code>{w.pubkey}</code>\n\n"
        "Back up the key with 🔐 Export key. If the bot's database or encryption key is lost, so is the wallet.",
        back_kb([Btn("Open wallet", callback_data=f"w:view:{w.id}")]),
    )


async def start_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _check_limit(context, update.effective_user.id):
        await reply(update, f"Wallet limit reached ({config.MAX_WALLETS_PER_USER}).", back_kb())
        return
    set_awaiting(context, "import_key")
    await reply(
        update,
        "📥 Send the wallet's private key (base58, or a JSON byte array).\n\n"
        "I'll delete your message right after reading it.",
        cancel_kb(),
    )


async def receive_import(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    try:
        await update.message.delete()
    except Exception:
        pass
    try:
        kp = parse_secret_key(text)
    except ValueError as e:
        await reply(update, f"❌ {esc(e)}. Try again or tap Cancel.", cancel_kb())
        return
    s = svc(context)
    user_id = update.effective_user.id
    pubkey = str(kp.pubkey())
    if any(w.pubkey == pubkey for w in s.db.list_wallets(user_id)):
        set_awaiting(context, None)
        await reply(update, "That wallet is already added.", back_kb([Btn("🔑 Wallets", callback_data="w:list")]))
        return
    n = len(s.db.list_wallets(user_id)) + 1
    w = s.db.add_wallet(user_id, f"Wallet {n}", pubkey, s.keystore.encrypt(kp))
    set_awaiting(context, None)
    await reply(
        update,
        f"✅ Imported <b>{esc(w.label)}</b>\n<code>{w.pubkey}</code>",
        back_kb([Btn("Open wallet", callback_data=f"w:view:{w.id}")]),
    )


async def make_default(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    svc(context).db.set_default_wallet(update.effective_user.id, wallet_id)
    await show_wallet(update, context, wallet_id)


async def confirm_export(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    await reply(
        update,
        "⚠️ Your private key gives full control of this wallet. Never share it with anyone, including support.\n\n"
        f"The message will delete itself after {EXPORT_TTL_SECONDS}s.",
        InlineKeyboardMarkup(
            [[Btn("Show key", callback_data=f"w:exportok:{wallet_id}")], [Btn("⬅️ Back", callback_data=f"w:view:{wallet_id}")]]
        ),
        edit=True,
    )


async def _delete_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, message_id = context.job.data
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    s = svc(context)
    w = s.db.get_wallet(update.effective_user.id, wallet_id)
    if not w:
        return
    secret = export_secret_key(s.keystore.decrypt(w.enc_secret))
    msg = await reply(update, f"🔐 <b>{esc(w.label)}</b> private key:\n<tg-spoiler><code>{secret}</code></tg-spoiler>")
    context.job_queue.run_once(_delete_message, EXPORT_TTL_SECONDS, data=(msg.chat_id, msg.message_id))


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    await reply(
        update,
        "🗑 Remove this wallet from the bot? Any funds stay on-chain, but you'll need the private key to access them.",
        InlineKeyboardMarkup(
            [
                [Btn("Yes, remove", callback_data=f"w:delok:{wallet_id}")],
                [Btn("⬅️ Back", callback_data=f"w:view:{wallet_id}")],
            ]
        ),
        edit=True,
    )


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    svc(context).db.delete_wallet(update.effective_user.id, wallet_id)
    await show_list(update, context)


async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int) -> None:
    set_awaiting(context, "withdraw_address", wallet_id=wallet_id)
    await reply(update, "📤 Send the destination Solana address.", cancel_kb())


async def receive_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: dict) -> None:
    if not is_pubkey(text):
        await reply(update, "❌ That isn't a valid Solana address. Try again or tap Cancel.", cancel_kb())
        return
    set_awaiting(context, "withdraw_amount", wallet_id=state["wallet_id"], to=text.strip())
    await reply(update, "How much SOL? Send a number, or <b>max</b>.", cancel_kb())


async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: dict) -> None:
    s = svc(context)
    w = s.db.get_wallet(update.effective_user.id, state["wallet_id"])
    if not w:
        set_awaiting(context, None)
        return
    balance = int(round(await s.rpc.balance_sol(w.pubkey) * LAMPORTS_PER_SOL))
    if text.strip().lower() == "max":
        lamports = balance - TX_FEE_LAMPORTS
    else:
        try:
            lamports = int(round(float(text) * LAMPORTS_PER_SOL))
        except ValueError:
            await reply(update, "❌ Send a number like 0.5, or max.", cancel_kb())
            return
    if lamports <= 0 or lamports + TX_FEE_LAMPORTS > balance:
        await reply(update, f"❌ Not enough SOL. Balance: {balance / LAMPORTS_PER_SOL:.4f} SOL.", cancel_kb())
        return
    set_awaiting(context, None)
    kp = s.keystore.decrypt(w.enc_secret)
    signature = await s.rpc.transfer_sol(kp, state["to"], lamports)
    desc = f"Withdraw {lamports / LAMPORTS_PER_SOL:.4f} SOL to {short(state['to'])}"
    s.db.track_tx(signature, update.effective_user.id, update.effective_chat.id, "withdraw", desc)
    await reply(update, f"⏳ <b>Submitted</b>: {esc(desc)}\nTx: {tx_link(signature)}", InlineKeyboardMarkup([[HOME_BTN]]))
