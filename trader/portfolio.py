from telegram import InlineKeyboardButton as Btn, Update
from telegram.ext import ContextTypes

from .common import back_kb, esc, fmt_num, reply, require_wallet, short, svc
from .market import SOL_MINT

MAX_ROWS = 15


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = svc(context)
    if not await require_wallet(update, context):
        return
    wallets = s.db.list_wallets(update.effective_user.id)
    per_wallet = []
    mints = {SOL_MINT}
    for w in wallets:
        sol = await s.rpc.balance_sol(w.pubkey)
        holdings = await s.rpc.token_holdings(w.pubkey)
        mints.update(h.mint for h in holdings)
        per_wallet.append((w, sol, holdings))
    prices = await s.market.prices_usd(sorted(mints))
    sol_price = prices.get(SOL_MINT)

    lines = ["📁 <b>Portfolio</b>\n"]
    total = 0.0
    token_buttons = []
    for w, sol, holdings in per_wallet:
        sol_usd = sol * sol_price if sol_price else None
        total += sol_usd or 0
        lines.append(f"<b>{esc(w.label)}</b> ({short(w.pubkey)})")
        lines.append(f"  ◎ {sol:.4f} SOL" + (f" · ${sol_usd:,.2f}" if sol_usd is not None else ""))
        rows = []
        for h in holdings:
            usd = h.amount * prices[h.mint] if h.mint in prices else None
            total += usd or 0
            rows.append((usd or 0, h, usd))
        rows.sort(key=lambda r: r[0], reverse=True)
        for _, h, usd in rows[:MAX_ROWS]:
            value = f" · ${usd:,.2f}" if usd is not None else ""
            lines.append(f"  • <code>{short(h.mint)}</code> {fmt_num(h.amount)}{value}")
            if len(token_buttons) < MAX_ROWS and all(b.callback_data != f"t:view:{h.mint}" for b in token_buttons):
                token_buttons.append(Btn(short(h.mint), callback_data=f"t:view:{h.mint}"))
        if len(rows) > MAX_ROWS:
            lines.append(f"  … and {len(rows) - MAX_ROWS} more")
        lines.append("")
    lines.append(f"Total value: <b>${total:,.2f}</b>")
    lines.append("\nTap a token to trade it, or paste any token address.")
    button_rows = [token_buttons[i : i + 3] for i in range(0, len(token_buttons), 3)]
    button_rows.append([Btn("🔄 Refresh", callback_data="p:show")])
    await reply(update, "\n".join(lines), back_kb(*button_rows), edit=True)
