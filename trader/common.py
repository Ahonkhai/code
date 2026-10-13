import html
import json
from dataclasses import dataclass

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import config
from .db import Database, Wallet
from .keystore import Keystore
from .market import MarketClient
from .pump import PumpClient
from .solana_rpc import SolanaRpc


@dataclass
class Services:
    db: Database
    keystore: Keystore
    rpc: SolanaRpc
    pump: PumpClient
    market: MarketClient


def svc(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.application.bot_data["svc"]


def esc(text) -> str:
    return html.escape(str(text))


def short(addr: str) -> str:
    return f"{addr[:4]}…{addr[-4:]}"


def fmt_num(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    if value >= 1:
        return f"{value:.2f}"
    return f"{value:.6g}"


def tx_link(signature: str) -> str:
    return f'<a href="{config.EXPLORER_TX_URL.format(signature)}">{short(signature)}</a>'


WELCOME = (
    "🚀 <b>Welcome to {name}</b>\n\n"
    "Create and trade tokens on Solana launch platforms.\n\n"
    "⚙️ <b>Advanced</b>\n"
    "• Sniper protection\n"
    "• Token safety checks\n"
    "• Tx tracker\n\n"
    "Tap a button below to begin:"
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [Btn("🚀 Launch", callback_data="l:start"), Btn("🔑 Wallets", callback_data="w:list")],
            [Btn("📁 Portfolio", callback_data="p:show")],
            [Btn("🧾 Tx tracker", callback_data="x:list"), Btn("🛡 Settings", callback_data="s:show")],
        ]
    )


CANCEL_BTN = Btn("❌ Cancel", callback_data="m:cancel")
HOME_BTN = Btn("⬅️ Menu", callback_data="m:home")


def cancel_kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([*rows, [CANCEL_BTN]])


def back_kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([*rows, [HOME_BTN]])


def is_allowed(user_id: int) -> bool:
    if not config.REQUIRE_VERIFIED:
        return True
    try:
        with open(config.VERIFIED_USERS_FILE, encoding="utf-8") as f:
            content = f.read().strip()
        return str(user_id) in (json.loads(content) if content else {})
    except (OSError, ValueError):
        return False


async def reply(update: Update, text: str, kb: InlineKeyboardMarkup | None = None, edit: bool = False):
    """Edit the message behind a button press when asked, otherwise send a new message."""
    if edit and update.callback_query and update.callback_query.message:
        try:
            return await update.callback_query.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True
            )
        except Exception:
            pass
    return await update.effective_chat.send_message(
        text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True
    )


def set_awaiting(context: ContextTypes.DEFAULT_TYPE, kind: str | None, **data) -> None:
    if kind is None:
        context.user_data.pop("awaiting", None)
    else:
        context.user_data["awaiting"] = {"kind": kind, **data}


def awaiting(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get("awaiting")


async def require_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Wallet | None:
    wallet = svc(context).db.default_wallet(update.effective_user.id)
    if not wallet:
        await reply(
            update,
            "You don't have a wallet yet. Create or import one first.",
            InlineKeyboardMarkup([[Btn("🔑 Wallets", callback_data="w:list")], [HOME_BTN]]),
        )
    return wallet


async def submit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, signed: bytes, kind: str, description: str
) -> str:
    """Send a signed transaction and register it with the tx tracker."""
    s = svc(context)
    signature = await s.rpc.send_raw(signed)
    s.db.track_tx(signature, update.effective_user.id, update.effective_chat.id, kind, description)
    await reply(update, f"⏳ <b>Submitted</b>: {esc(description)}\nTx: {tx_link(signature)}\n\nI'll message you when it confirms.")
    return signature
