from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import config
from .common import HOME_BTN, cancel_kb, esc, fmt_num, reply, require_wallet, set_awaiting, short, submit, svc
from .solana_rpc import sign_versioned

BUY_PRESETS = ("0.1", "0.5", "1")
SELL_PRESETS = (25, 50, 100)
# SOL kept back for token-account rent and fees when buying.
BUY_BUFFER_SOL = 0.003


def token_kb(mint: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [Btn(f"Buy {a} SOL", callback_data=f"t:buy:{mint}:{a}") for a in BUY_PRESETS],
            [Btn("Buy X SOL", callback_data=f"t:buyx:{mint}"), Btn("🔄 Refresh", callback_data=f"t:view:{mint}")],
            [Btn(f"Sell {p}%", callback_data=f"t:sell:{mint}:{p}") for p in SELL_PRESETS],
            [HOME_BTN],
        ]
    )


async def show_token(update: Update, context: ContextTypes.DEFAULT_TYPE, mint: str, edit: bool = False) -> None:
    s = svc(context)
    info = await s.rpc.mint_info(mint)
    if not info:
        await reply(update, "❌ That address isn't a token mint.", InlineKeyboardMarkup([[HOME_BTN]]))
        return
    prices = await s.market.prices_usd([mint])
    price = prices.get(mint)
    lines = [f"🪙 <b>Token</b> <code>{mint}</code>\n"]
    if price is not None:
        lines.append(f"Price: ${price:.8g} · Market cap: ${fmt_num(price * info.supply)}")
    lines.append(f"Supply: {fmt_num(info.supply)}\n")

    # Safety checks
    lines.append("🛡 <b>Safety</b>")
    lines.append(("✅ Mint authority revoked" if not info.mint_authority else "⚠️ Creator can still mint more tokens"))
    lines.append(("✅ Freeze authority revoked" if not info.freeze_authority else "⚠️ Creator can freeze holders' tokens"))
    try:
        holders = await s.rpc.largest_holders(mint)
        if holders and info.supply:
            top10 = sum(a for _, a in holders[:10]) / info.supply * 100
            top1 = holders[0][1] / info.supply * 100
            flag = "⚠️" if top1 > 20 else "✅"
            lines.append(f"{flag} Top holder {top1:.1f}% · Top 10 {top10:.1f}% (includes bonding curve / pool)")
    except Exception:
        pass

    wallet = s.db.default_wallet(update.effective_user.id)
    if wallet:
        held = next((h.amount for h in await s.rpc.token_holdings(wallet.pubkey) if h.mint == mint), 0)
        lines.append(f"\nYou hold: {fmt_num(held)} ({esc(wallet.label)})")
    lines.append(f'\n<a href="{config.EXPLORER_TOKEN_URL.format(mint)}">View chart</a>')
    await reply(update, "\n".join(lines), token_kb(mint), edit=edit)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE, mint: str, sol: float) -> None:
    s = svc(context)
    wallet = await require_wallet(update, context)
    if not wallet:
        return
    settings = s.db.get_settings(update.effective_user.id)
    balance = await s.rpc.balance_sol(wallet.pubkey)
    needed = sol + settings.priority_fee + BUY_BUFFER_SOL
    if balance < needed:
        await reply(update, f"❌ Not enough SOL: {balance:.4f} available, about {needed:.4f} needed.")
        return
    try:
        raw = await s.pump.build_buy(wallet.pubkey, mint, sol, settings.slippage, settings.priority_fee)
        signed = sign_versioned(raw, [s.keystore.decrypt(wallet.enc_secret)])
        await submit(update, context, signed, "buy", f"Buy {sol} SOL of {short(mint)}")
    except Exception as e:
        await reply(update, f"❌ Buy failed: {esc(e)}")


async def start_buy_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, mint: str) -> None:
    set_awaiting(context, "buy_amount", mint=mint)
    await reply(update, "How much SOL do you want to spend?", cancel_kb())


async def receive_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, state: dict) -> None:
    try:
        sol = float(text)
    except ValueError:
        sol = 0
    if sol <= 0:
        await reply(update, "❌ Send a positive SOL amount like 0.25.", cancel_kb())
        return
    set_awaiting(context, None)
    await buy(update, context, state["mint"], sol)


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE, mint: str, percent: int) -> None:
    s = svc(context)
    wallet = await require_wallet(update, context)
    if not wallet:
        return
    held = next((h.amount for h in await s.rpc.token_holdings(wallet.pubkey) if h.mint == mint), 0)
    if held <= 0:
        await reply(update, f"❌ {esc(wallet.label)} doesn't hold this token.")
        return
    settings = s.db.get_settings(update.effective_user.id)
    try:
        raw = await s.pump.build_sell(wallet.pubkey, mint, percent, settings.slippage, settings.priority_fee)
        signed = sign_versioned(raw, [s.keystore.decrypt(wallet.enc_secret)])
        await submit(update, context, signed, "sell", f"Sell {percent}% of {short(mint)}")
    except Exception as e:
        await reply(update, f"❌ Sell failed: {esc(e)}")
