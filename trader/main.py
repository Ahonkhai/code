import logging
import re

import httpx
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import config, launch, portfolio, settings, tracker, trade, wallets
from .common import WELCOME, Services, awaiting, is_allowed, main_menu, reply, set_awaiting
from .db import Database
from .keystore import Keystore
from .market import MarketClient
from .pump import PumpClient
from .solana_rpc import SolanaRpc, is_pubkey

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
NOT_ALLOWED = "This bot is for verified members only."


def allowed(update: Update) -> bool:
    return bool(update.effective_user) and is_allowed(update.effective_user.id)


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> None:
    set_awaiting(context, None)
    context.user_data.pop("launch", None)
    await reply(update, WELCOME.format(name=config.BOT_NAME), main_menu(), edit=edit)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        await update.effective_chat.send_message(NOT_ALLOWED)
        return
    await home(update, context)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not allowed(update):
        await update.effective_chat.send_message(NOT_ALLOWED)
        return
    parts = (query.data or "").split(":")
    area, action, args = parts[0], parts[1] if len(parts) > 1 else "", parts[2:]

    if area == "m":
        if action == "cancel":
            set_awaiting(context, None)
            context.user_data.pop("launch", None)
            await reply(update, "❌ Cancelled.")
        await home(update, context, edit=action == "home")

    elif area == "w":
        wid = int(args[0]) if args else 0
        handler = {
            "list": lambda: wallets.show_list(update, context),
            "new": lambda: wallets.create(update, context),
            "import": lambda: wallets.start_import(update, context),
            "view": lambda: wallets.show_wallet(update, context, wid),
            "default": lambda: wallets.make_default(update, context, wid),
            "export": lambda: wallets.confirm_export(update, context, wid),
            "exportok": lambda: wallets.export(update, context, wid),
            "del": lambda: wallets.confirm_delete(update, context, wid),
            "delok": lambda: wallets.delete(update, context, wid),
            "withdraw": lambda: wallets.start_withdraw(update, context, wid),
        }.get(action)
        if handler:
            await handler()

    elif area == "l":
        if action == "start":
            await launch.start(update, context)
        elif action in ("latest", "hot"):
            await launch.show_trending(update, context, action)
        elif action == "dev":
            await launch.dev_buy_button(update, context, args[0])
        elif action == "soc":
            await launch.ask_social(update, context, args[0])
        elif action in ("socdone", "socskip"):
            await launch.finish_socials(update, context, skip=action == "socskip")
        elif action == "confirm":
            await query.edit_message_reply_markup(None)
            await launch.confirm(update, context)

    elif area == "t":
        mint = args[0] if args else ""
        if not is_pubkey(mint):
            return
        if action == "view":
            await trade.show_token(update, context, mint, edit=True)
        elif action == "buy":
            await trade.buy(update, context, mint, float(args[1]))
        elif action == "buyx":
            await trade.start_buy_custom(update, context, mint)
        elif action == "sell":
            await trade.sell(update, context, mint, int(args[1]))

    elif area == "p":
        await portfolio.show(update, context)

    elif area == "x":
        await tracker.show(update, context)

    elif area == "s":
        if action == "show":
            await settings.show(update, context)
        elif action == "slip":
            await settings.set_value(update, context, "slippage", float(args[0]))
        elif action == "fee":
            await settings.set_value(update, context, "priority_fee", float(args[0]))
        elif action == "slipx":
            await settings.start_custom(update, context, "slippage")
        elif action == "feex":
            await settings.start_custom(update, context, "priority_fee")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        await update.effective_chat.send_message(NOT_ALLOWED)
        return
    text = update.message.text.strip()
    state = awaiting(context)
    kind = state["kind"] if state else None

    if kind == "import_key":
        await wallets.receive_import(update, context, text)
    elif kind == "withdraw_address":
        await wallets.receive_withdraw_address(update, context, text, state)
    elif kind == "withdraw_amount":
        await wallets.receive_withdraw_amount(update, context, text, state)
    elif kind == "launch_social":
        await launch.receive_social(update, context, text, state)
    elif kind and kind.startswith("launch_"):
        await launch.receive_text(update, context, kind, text)
    elif kind == "buy_amount":
        await trade.receive_buy_amount(update, context, text, state)
    elif kind in ("set_slippage", "set_priority_fee"):
        await settings.receive_custom(update, context, kind.removeprefix("set_"), text)
    elif MINT_RE.match(text) and is_pubkey(text):
        await trade.show_token(update, context, text)
    else:
        await home(update, context)


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    state = awaiting(context)
    if state and state["kind"] == "launch_image":
        await launch.receive_image(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message("⚠️ Something went wrong. Please try again.")
        except Exception:
            pass


async def post_init(app: Application) -> None:
    http = httpx.AsyncClient(headers={"User-Agent": f"{config.BOT_NAME}/1.0"})
    app.bot_data["http"] = http
    app.bot_data["svc"] = Services(
        db=Database(),
        keystore=Keystore(config.WALLET_ENCRYPTION_KEY),
        rpc=SolanaRpc(config.SOLANA_RPC_URL, http),
        pump=PumpClient(http),
        market=MarketClient(http),
    )
    app.job_queue.run_repeating(tracker.poll, interval=tracker.POLL_SECONDS, first=tracker.POLL_SECONDS)


async def post_shutdown(app: Application) -> None:
    http = app.bot_data.get("http")
    if http:
        await http.aclose()


def build_app() -> Application:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("Set TRADER_TELEGRAM_TOKEN (or TELEGRAM_TOKEN) in .env")
    if not config.WALLET_ENCRYPTION_KEY:
        raise SystemExit(
            "Set WALLET_ENCRYPTION_KEY in .env. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(True)
        .build()
    )
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["start", "menu"], start_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(private & (filters.PHOTO | filters.Document.IMAGE), on_media))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
