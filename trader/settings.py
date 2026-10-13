from telegram import InlineKeyboardButton as Btn, Update
from telegram.ext import ContextTypes

from .common import back_kb, cancel_kb, reply, set_awaiting, svc

SLIPPAGE_PRESETS = (5, 10, 15, 25)
FEE_PRESETS = (0.0001, 0.0005, 0.001, 0.005)


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = svc(context).db.get_settings(update.effective_user.id)
    text = (
        "🛡 <b>Sniper protection & trade settings</b>\n\n"
        f"Max slippage: <b>{s.slippage:g}%</b>\n"
        "Trades that would fill worse than this (e.g. a sniper or sandwich bot moving the price first) fail instead of filling.\n\n"
        f"Priority fee: <b>{s.priority_fee:g} SOL</b>\n"
        "Higher fees land your launch or trade sooner, ahead of slower bots."
    )
    rows = [
        [Btn(("• " if s.slippage == p else "") + f"{p}%", callback_data=f"s:slip:{p}") for p in SLIPPAGE_PRESETS],
        [Btn(("• " if s.priority_fee == f else "") + f"{f:g}", callback_data=f"s:fee:{f}") for f in FEE_PRESETS],
        [Btn("Custom slippage", callback_data="s:slipx"), Btn("Custom fee", callback_data="s:feex")],
    ]
    await reply(update, text, back_kb(*rows), edit=True)


async def set_value(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, value: float) -> None:
    svc(context).db.update_settings(update.effective_user.id, **{field: value})
    await show(update, context)


async def start_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str) -> None:
    set_awaiting(context, f"set_{field}")
    prompt = "Send max slippage in % (0.5-50)." if field == "slippage" else "Send priority fee in SOL (0-0.1)."
    await reply(update, prompt, cancel_kb())


async def receive_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, text: str) -> None:
    limits = {"slippage": (0.5, 50), "priority_fee": (0, 0.1)}[field]
    try:
        value = float(text.strip().rstrip("%"))
    except ValueError:
        value = -1
    if not limits[0] <= value <= limits[1]:
        await reply(update, f"❌ Send a number between {limits[0]:g} and {limits[1]:g}.", cancel_kb())
        return
    set_awaiting(context, None)
    svc(context).db.update_settings(update.effective_user.id, **{field: value})
    await show(update, context)
