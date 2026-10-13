import io
import re

from PIL import Image, UnidentifiedImageError
from solders.keypair import Keypair
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
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
MIN_IMAGE_PX = 512
# Width/height may differ by this fraction and still count as square.
SQUARE_TOLERANCE = 0.01
IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpg"}
# Rough SOL needed on top of the dev buy: mint/metadata rent plus fees.
LAUNCH_OVERHEAD_SOL = 0.03

NAME_PROMPT = "📝 <b>Token name</b> (1-{max})\nTip: Latest, Hot Tokens."
SYMBOL_PROMPT = f"🔤 Enter <b>SYMBOL</b> ({SYMBOL_MIN}-{SYMBOL_MAX}, A-Z)\nExample: $PEPE"
SOCIALS_PROMPT = "🔗 Add socials (optional): choose a platform or skip."
# key: (icon, label, example)
SOCIALS = {
    "twitter": ("🐦", "X", "https://x.com/yourtoken or @yourtoken"),
    "telegram": ("📱", "Telegram", "https://t.me/yourtoken or @yourtoken"),
    "website": ("🌐", "Website", "https://yourtoken.com"),
    "instagram": ("📸", "Instagram", "https://instagram.com/yourtoken or @yourtoken"),
}
HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
URL_RE = re.compile(r"^https?://[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?(/\S*)?$")
# SOL bought by the creator wallet in the launch transaction.
TRADE_SIZES = (5, 10, 15, 25)
TRADE_SIZE_PROMPT = "💰 <b>Choose trade size</b>\nSOL your wallet buys at launch. Tap a size or type an amount."
IMAGE_PROMPT = f"📷 <b>Upload token image</b>\nPNG/JPG · Square · ≥{MIN_IMAGE_PX}px"
DESC_PROMPT = f"📝 Send the exact description of the token (≤ {DESC_MAX} chars)\n1-2 lines. Avoid links."


def _name_kb() -> InlineKeyboardMarkup:
    return cancel_kb([Btn("🆕 Latest", callback_data="l:latest"), Btn("🔥 Hot", callback_data="l:hot")])


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
        await reply(update, IMAGE_PROMPT, cancel_kb())

    elif kind == "launch_devbuy":
        try:
            amount = float(text)
        except ValueError:
            amount = 0
        if amount <= 0:
            await reply(update, f"❌ Pick a size or send a SOL amount like 3.\n\n{TRADE_SIZE_PROMPT}", _trade_size_kb())
            return
        await _set_dev_buy(update, context, amount)


async def _ask_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_awaiting(context, "launch_image")
    await reply(update, IMAGE_PROMPT, cancel_kb())


def check_image(raw: bytes) -> str:
    """Validate a token image and return its file extension; raises ValueError with a user-facing reason."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt, (w, h) = img.format, img.size
    except (UnidentifiedImageError, OSError):
        raise ValueError("That file isn't a readable image.")
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"Image must be PNG or JPG (got {fmt}).")
    if abs(w - h) > SQUARE_TOLERANCE * max(w, h):
        raise ValueError(f"Image must be square (got {w}×{h}px).")
    if min(w, h) < MIN_IMAGE_PX:
        raise ValueError(f"Image must be at least {MIN_IMAGE_PX}px (got {w}×{h}px).")
    return IMAGE_FORMATS[fmt]


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg.photo:
        tg_file = msg.photo[-1]
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        tg_file = msg.document
    else:
        await reply(update, f"❌ That isn't an image.\n\n{IMAGE_PROMPT}", cancel_kb())
        return
    if tg_file.file_size and tg_file.file_size > MAX_IMAGE_BYTES:
        await reply(update, f"❌ Image is over 5 MB.\n\n{IMAGE_PROMPT}", cancel_kb())
        return
    file = await tg_file.get_file()
    raw = bytes(await file.download_as_bytearray())
    try:
        ext = check_image(raw)
    except ValueError as e:
        await reply(update, f"❌ {esc(e)}\n\n{IMAGE_PROMPT}", cancel_kb())
        return
    data = context.user_data.setdefault("launch", {})
    data["image"] = raw
    data["image_name"] = f"image.{ext}"
    await _ask_dev_buy(update, context)


async def _ask_dev_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_awaiting(context, "launch_devbuy")
    await reply(update, TRADE_SIZE_PROMPT, _trade_size_kb())


def _trade_size_kb() -> InlineKeyboardMarkup:
    rows = [TRADE_SIZES[i : i + 2] for i in range(0, len(TRADE_SIZES), 2)]
    return cancel_kb(*[[Btn(f"{a} SOL", callback_data=f"l:dev:{a}") for a in row] for row in rows])


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
            f"Fund <code>{wallet.pubkey}</code> or pick a smaller size.",
            _trade_size_kb(),
        )
        return
    data["dev_buy"] = amount
    data.setdefault("socials", {})
    await show_socials(update, context)


def _socials_kb(socials: dict) -> InlineKeyboardMarkup:
    def btn(key: str) -> Btn:
        icon, label, _ = SOCIALS[key]
        return Btn(f"{'✅' if socials.get(key) else icon} {label}", callback_data=f"l:soc:{key}")

    return cancel_kb(
        [btn("twitter"), btn("telegram")],
        [btn("website"), btn("instagram")],
        [Btn("✅ Done", callback_data="l:socdone"), Btn("⏭ Skip", callback_data="l:socskip")],
    )


async def show_socials(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    set_awaiting(context, None)
    socials = (context.user_data.get("launch") or {}).get("socials", {})
    added = "".join(f"\n{SOCIALS[k][0]} {esc(v)}" for k, v in socials.items())
    await reply(update, f"{note}{SOCIALS_PROMPT}{added}", _socials_kb(socials))


async def ask_social(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    if key not in SOCIALS:
        return
    set_awaiting(context, "launch_social", platform=key)
    icon, label, example = SOCIALS[key]
    await reply(update, f"{icon} Send your {label} link or @handle\nExample: {example}", cancel_kb())


def normalize_social(key: str, text: str) -> str:
    """Turn a link or @handle into a full https URL; raises ValueError if it doesn't fit the platform."""
    text = text.strip()
    if " " in text or not text:
        raise ValueError("Send a single link or @handle.")
    hosts = {"twitter": ("x.com", "twitter.com"), "telegram": ("t.me", "telegram.me"), "instagram": ("instagram.com",)}
    if key in hosts:
        if text.startswith("@"):
            if not HANDLE_RE.match(text[1:]):
                raise ValueError("That handle has invalid characters.")
            return f"https://{hosts[key][0]}/{text[1:]}"
        url = text if "://" in text else f"https://{text}"
        host = url.split("://", 1)[1].split("/", 1)[0].lower().removeprefix("www.")
        if host not in hosts[key] or "/" not in url.split("://", 1)[1]:
            raise ValueError(f"That isn't a valid {SOCIALS[key][1]} link.")
        return url
    url = text if "://" in text else f"https://{text}"
    if not URL_RE.match(url):
        raise ValueError("That isn't a valid website link.")
    return url


async def receive_social(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: dict) -> None:
    key = state["platform"]
    try:
        url = normalize_social(key, text)
    except ValueError as e:
        await reply(update, f"❌ {esc(e)} Try again or tap Cancel.", cancel_kb())
        return
    context.user_data.setdefault("launch", {}).setdefault("socials", {})[key] = url
    await show_socials(update, context, note=f"✅ {SOCIALS[key][1]} set\n\n")


async def finish_socials(update: Update, context: ContextTypes.DEFAULT_TYPE, skip: bool) -> None:
    data = context.user_data.get("launch") or {}
    if "dev_buy" not in data:
        await reply(update, "That launch expired. Start again from the menu.", InlineKeyboardMarkup([[CANCEL_BTN]]))
        return
    if skip:
        data["socials"] = {}
    await _show_confirm(update, context)


async def _show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_awaiting(context, None)
    data = context.user_data["launch"]
    wallet = await require_wallet(update, context)
    if not wallet:
        return
    socials = ", ".join(f"{SOCIALS[k][1]} {esc(v)}" for k, v in data.get("socials", {}).items()) or "—"
    caption = (
        "<b>Review</b>\n\n"
        f"📝 Name: {esc(data['name'])}\n"
        f"🔤 Symbol: ${esc(data['symbol'])}\n"
        f"💰 Trade size: {data['dev_buy']:g} SOL\n"
        f"📄 Description: {esc(data.get('description') or '—')}\n"
        f"🔗 Socials: {socials}\n"
        f"🔑 Wallet: {esc(wallet.label)} ({short(wallet.pubkey)})"
    )
    await update.effective_chat.send_photo(
        data["image"],
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb([Btn("✅ Confirm & Save", callback_data="l:confirm")]),
    )


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
        **data.get("socials", {}),
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
