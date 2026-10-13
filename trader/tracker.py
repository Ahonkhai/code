import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .common import back_kb, esc, reply, svc, tx_link

log = logging.getLogger(__name__)

POLL_SECONDS = 4
# A tx the cluster still doesn't know about after this long was dropped (blockhash expired).
EXPIRE_SECONDS = 150
STATUS_ICON = {"pending": "⏳", "confirmed": "✅", "failed": "❌", "expired": "⌛"}


async def poll(context: ContextTypes.DEFAULT_TYPE) -> None:
    s = svc(context)
    pending = s.db.pending_txs()
    for i in range(0, len(pending), 256):
        chunk = pending[i : i + 256]
        try:
            statuses = await s.rpc.signature_statuses([t.signature for t in chunk])
        except Exception as e:
            log.warning("status poll failed: %s", e)
            return
        for tx, st in zip(chunk, statuses):
            if st is None:
                if time.time() - tx.created_at > EXPIRE_SECONDS:
                    new, note = "expired", "dropped by the network (try again, maybe with a higher priority fee)"
                else:
                    continue
            elif st.get("err"):
                new, note = "failed", f"error: {st['err']}"
            elif st.get("confirmationStatus") in ("confirmed", "finalized"):
                new, note = "confirmed", "confirmed"
            else:
                continue
            s.db.set_tx_status(tx.signature, new)
            try:
                await context.bot.send_message(
                    tx.chat_id,
                    f"{STATUS_ICON[new]} <b>{esc(tx.description)}</b>: {esc(note)}\nTx: {tx_link(tx.signature)}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.warning("could not notify %s: %s", tx.chat_id, e)


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txs = svc(context).db.recent_txs(update.effective_user.id)
    lines = ["🧾 <b>Tx tracker</b>: last 10\n"]
    for t in txs:
        when = time.strftime("%b %d %H:%M", time.gmtime(t.created_at))
        lines.append(f"{STATUS_ICON.get(t.status, '•')} {esc(t.description)}\n    {when} UTC · {tx_link(t.signature)}")
    if not txs:
        lines.append("No transactions yet.")
    await reply(update, "\n".join(lines), back_kb(), edit=True)
