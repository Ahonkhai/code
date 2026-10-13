import re

from solders.keypair import Keypair
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .common import CANCEL_BTN, cancel_kb, esc, fmt_num, reply, require_wallet, set_awaiting, short, submit, svc
from . import config
from .pump import TokenMeta
from .solana_rpc import sign_versioned

# On-chain token metadata caps name at 32 and symbol at 10 bytes; longer values fail the launch tx.
NAME_MAX = 32
SYMBOL_MIN, SYMBOL_MAX = 2, 10
SYMBOL_RE = re.compile(rf"^[A-Z]{{{SYMBOL_MIN},{SYMBOL_MAX}}}$")
DESC_MAX = 500
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Rough SOL needed on top of the dev buy: mint/metadata rent plus fees.
LAUNCH_OVERHEAD_SOL = 0.03

NAME_PROMPT = "📝 <b>Token name</b> (1-{max})\nTip: Latest, Hot Tokens."
SYMBOL_PROMPT = f"🔤 Enter <b>SYMBOL</b> ({SYMBOL_MIN}-{SYMBOL_MAX}, A-Z)\nExample: $PEPE"
DESC_PROMPT = f"📝 Send the exact description of the token (≤ {DESC_MAX} chars)\n1-2 lines. Avoid links."


def _name_kb() -> InlineKeyboardMarkup:
    return cancel_kb([Btn("🆕 Latest", callback_data="l:latest"), Btn("🔥 Hot", callback_data="l:hot")])


def _skip_kb(step: str) -> InlineKeyboardMarkup:
    return cancel_kb([Btn("⏭ Skip", callback_data=f"l:skip:{step}")])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_wallet(update, context):
        return
    context.user_data["launch"] = {}
    set_awaiting(context, "launch_name")
    await reply(update, NAME_PROMPT.format(max=NAME_MAX), _name_kb())


async def show_trending(update: Update, context: ContextTypes.DEFAULT_TYPE, which: str) -> None:
    market = svc(context).market
    try:
        coins = await (market.hot() if which == "hot" else market.latest())
    except Exception:
        await reply(update, "Couldn't load tokens right now.", _name_kb())
        return
    title = "🔥 Hot tokens" if which == "hot" else "🆕 Latest tokens"
    lines = [f"<b>{title}</b>\n"]
    for c in coins:
        mc = f" · ${fmt_num(c.market_cap_usd)}" if c.market_cap_usd else ""
        lines.append(f"• <b>{esc(c.name)}</b> (${esc(c.symbol)}){mc}")
    lines.append("\n" + NAME_PROMPT.format(max=NAME_MAX))
    await reply(update, "\n".join(lines), _name_kb())


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, text: str) -> None:
    data = context.user_data.setdefault("launch", {})
    text = text.strip()

    if kind == "launch_name":
        if not 1 <= len(text) <= NAME_MAX:
            await reply(update, f"❌ Name must be 1-{NAME_MAX} characters.", _name_kb())
            return
        data["name"] = text
        set_awaiting(context, "launch_symbol")
        await reply(update, f"✅ Name set: {esc(text)}\n\n{SYMBOL_PROMPT}", cancel_kb())

    elif kind == "launch_symbol":
        symbol = text.lstrip("$").upper()
        if not SYMBOL_RE.match(symbol):
            await reply(update, f"❌ Symbol must be {SYMBOL_MIN}-{SYMBOL_MAX} letters A-Z.\n\n{SYMBOL_PROMPT}", cancel_kb())
            return
        data["symbol"] = symbol
        set_awaiting(context, "launch_desc")
        await reply(update, f"✅ Symbol set: ${symbol}\n\n{DESC_PROMPT}", cancel_kb())

    elif kind == "launch_desc":
        if not 1 <= len(text) <= DESC_MAX:
            await reply(update, f"❌ Description must be 1-{DESC_MAX} characters.\n\n{DESC_PROMPT}", cancel_kb())
            return
        data["description"] = text
        await _ask_image(update, context)

    elif kind == "launch_image":
        await reply(update, "🖼 Please send an image (as a photo or file).", cancel_kb())

    elif kind == "launch_socials":
        for link in text.split():
            low = link.lower()
            if "t.me/" in low:
                data["telegram"] = link
            elif "x.com/" in low or "twitter.com/" in low:
                data["twitter"] = link
            else:
                data["website"] = link
        await _ask_dev_buy(update, context)

    elif kind == "launch_devbuy":
        try:
            amount = float(text)
        except ValueError:
            amount = -1
        if amount < 0:
            await reply(update, "❌ Send a SOL amount like 0.25 (or 0).", cancel_kb())
            return
        await _set_dev_buy(update, context, amount)


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE, step: str) -> None:
    if step == "socials":
        await _ask_dev_buy(update, context)


async def _ask_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_awaiting(context, "launch_image")
    await reply(update, "🖼 <b>Token image</b>: send a square image (PNG/JPG/GIF, max 5 MB).", cancel_kb())


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg.photo:
        tg_file, filename = msg.photo[-1], "image.jpg"
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        tg_file, filename = msg.document, msg.document.file_name or "image.png"
    else:
        await reply(update, "🖼 That isn't an image. Send a photo or an image file.", cancel_kb())
        return
    if tg_file.file_size and tg_file.file_size > MAX_IMAGE_BYTES:
        await reply(update, "❌ Image is over 5 MB.", cancel_kb())
        return
    file = await tg_file.get_file()
    data = context.user_data.setdefault("launch", {})
    data["image"] = bytes(await file.download_as_bytearray())
    data["image_name"] = filename
    set_awaiting(context, "launch_socials")
    await reply(
        update,
        "🔗 <b>Links</b> (optional): send your X/Twitter, Telegram and website links separated by spaces.",
        _skip_kb("socials"),
    )


async def _ask_dev_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_awaiting(context, "launch_devbuy")
    await reply(
        update,
        "💰 <b>Dev buy</b>: how much SOL should your wallet buy at launch?\n"
        "Pick an amount or type one. The buy is made openly from your default wallet.",
        cancel_kb(
            [Btn("0", callback_data="l:dev:0"), Btn("0.1", callback_data="l:dev:0.1"), Btn("0.5", callback_data="l:dev:0.5")],
            [Btn("1", callback_data="l:dev:1"), Btn("2", callback_data="l:dev:2")],
        ),
    )


async def _set_dev_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float) -> None:
    data = context.user_data.get("launch") or {}
    if not data.get("name") or not data.get("image"):
        set_awaiting(context, None)
        await reply(update, "That launch expired. Start again from the menu.", InlineKeyboardMarkup([[CANCEL_BTN]]))
        return
    s = svc(context)
    wallet = await require_wallet(update, context)
    if not wallet:
        return
    balance = await s.rpc.balance_sol(wallet.pubkey)
    settings = s.db.get_settings(update.effective_user.id)
    needed = amount + LAUNCH_OVERHEAD_SOL + settings.priority_fee
    if balance < needed:
        await reply(
            update,
            f"❌ {esc(wallet.label)} has {balance:.4f} SOL; this launch needs about {needed:.4f} SOL.\n"
            f"Fund <code>{wallet.pubkey}</code> or pick a smaller dev buy.",
            cancel_kb(),
        )
        return
    data["dev_buy"] = amount
    set_awaiting(context, None)
    links = "\n".join(f"{k.title()}: {esc(data[k])}" for k in ("twitter", "telegram", "website") if data.get(k))
    text = (
        "🚀 <b>Confirm launch</b>\n\n"
        f"Name: <b>{esc(data['name'])}</b>\n"
        f"Symbol: <b>${esc(data['symbol'])}</b>\n"
        f"Description: {esc(data.get('description') or '—')}\n"
        f"{links + chr(10) if links else ''}"
        f"Platform: pump.fun\n"
        f"Creator wallet: {esc(wallet.label)} ({short(wallet.pubkey)})\n"
        f"Dev buy: {amount} SOL\n"
        f"Slippage: {settings.slippage}% · Priority fee: {settings.priority_fee} SOL"
    )
    await reply(update, text, cancel_kb([Btn("✅ Launch", callback_data="l:confirm")]))


async def dev_buy_button(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: str) -> None:
    await _set_dev_buy(update, context, float(amount))


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data.pop("launch", None)
    if not data or "dev_buy" not in data:
        await reply(update, "That launch expired. Start again from the menu.", InlineKeyboardMarkup([[CANCEL_BTN]]))
        return
    s = svc(context)
    wallet = await require_wallet(update, context)
    if not wallet:
        return
    settings = s.db.get_settings(update.effective_user.id)
    meta = TokenMeta(
        name=data["name"],
        symbol=data["symbol"],
        description=data.get("description", ""),
        twitter=data.get("twitter", ""),
        telegram=data.get("telegram", ""),
        website=data.get("website", ""),
    )
    await reply(update, "⏳ Uploading metadata and building the launch transaction…")
    try:
        uri = await s.pump.upload_metadata(meta, data["image"], data["image_name"])
        mint_kp = Keypair()
        creator = s.keystore.decrypt(wallet.enc_secret)
        raw = await s.pump.build_create(
            str(creator.pubkey()), str(mint_kp.pubkey()), meta, uri, data["dev_buy"], settings.slippage, settings.priority_fee
        )
        signed = sign_versioned(raw, [mint_kp, creator])
        mint = str(mint_kp.pubkey())
        signature = await submit(update, context, signed, "launch", f"Launch ${meta.symbol}")
    except Exception as e:
        await reply(update, f"❌ Launch failed: {esc(e)}", InlineKeyboardMarkup([[CANCEL_BTN]]))
        return
    s.db.record_launch(mint, update.effective_user.id, meta.name, meta.symbol, signature)
    await reply(
        update,
        f"🪙 Mint: <code>{mint}</code>\n{config.EXPLORER_TOKEN_URL.format(mint)}",
        InlineKeyboardMarkup([[Btn("📊 Token", callback_data=f"t:view:{mint}")], [Btn("⬅️ Menu", callback_data="m:home")]]),
    )
