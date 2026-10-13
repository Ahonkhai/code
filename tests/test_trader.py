import base64
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from cryptography.fernet import Fernet
from PIL import Image
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction, VersionedTransaction

from trader import common, launch, main, trade, tracker, wallets
from trader.common import Services
from trader.db import Database
from trader.keystore import Keystore, export_secret_key, parse_secret_key
from trader.market import MarketClient
from trader.pump import PumpClient
from trader.solana_rpc import SolanaRpc, sign_versioned

PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")


def unsigned_tx(payer: Pubkey, extra_signers: list[Pubkey]) -> bytes:
    """An unsigned v0 tx shaped like the ones PumpPortal returns."""
    ix = Instruction(PROGRAM, b"\x01", [AccountMeta(p, True, True) for p in extra_signers])
    msg = MessageV0.try_compile(payer, [ix], [], Hash.default())
    return bytes(VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures))


class FakeChain:
    """httpx transport standing in for Solana RPC, pump.fun IPFS, PumpPortal and Jupiter."""

    def __init__(self):
        self.balances: dict[str, int] = {}
        self.sent: list[bytes] = []
        self.pumpportal: list[dict] = []
        self.statuses: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "rpc" in url:
            body = json.loads(request.content)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": self.rpc(body["method"], body["params"])})
        if "ipfs" in url:
            return httpx.Response(200, json={"metadataUri": "https://ipfs.example/meta.json"})
        if "trade-local" in url:
            payload = json.loads(request.content)
            self.pumpportal.append(payload)
            payer = Pubkey.from_string(payload["publicKey"])
            extra = [Pubkey.from_string(payload["mint"])] if payload["action"] == "create" else []
            return httpx.Response(200, content=unsigned_tx(payer, extra))
        if "price" in url:
            return httpx.Response(200, json={"So11111111111111111111111111111111111111112": {"usdPrice": 150.0}})
        return httpx.Response(404)

    def rpc(self, method, params):
        if method == "getBalance":
            return {"value": self.balances.get(params[0], 0)}
        if method == "sendTransaction":
            raw = base64.b64decode(params[0])
            self.sent.append(raw)
            try:
                tx = VersionedTransaction.from_bytes(raw)
            except Exception:
                tx = Transaction.from_bytes(raw)
            return str(tx.signatures[0])
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 1}}
        if method == "getTokenAccountsByOwner":
            return {"value": []}
        if method == "getSignatureStatuses":
            return {"value": [self.statuses.get(s) for s in params[0]]}
        raise AssertionError(f"unexpected rpc {method}")


class FakeContext:
    def __init__(self, services):
        self.user_data = {}
        self.application = SimpleNamespace(bot_data={"svc": services})
        self.job_queue = SimpleNamespace(run_once=lambda *a, **k: None)
        self.bot = SimpleNamespace(send_message=AsyncMock(), delete_message=AsyncMock())


def text_update(text: str, user_id: int = 42):
    message = SimpleNamespace(text=text, delete=AsyncMock(), photo=None, document=None)
    return SimpleNamespace(
        message=message,
        callback_query=None,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id, send_message=AsyncMock()),
    )


class TraderTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chain = FakeChain()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.chain))
        patcher = patch.multiple(
            "trader.config",
            PUMP_IPFS_URL="https://pump.test/api/ipfs",
            PUMPPORTAL_TRADE_URL="https://pumpportal.test/api/trade-local",
            JUPITER_PRICE_URL="https://jup.test/price/v3",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.services = Services(
            db=Database(os.path.join(self.tmp.name, "t.db")),
            keystore=Keystore(Fernet.generate_key().decode()),
            rpc=SolanaRpc("https://rpc.test", self.http),
            pump=PumpClient(self.http),
            market=MarketClient(self.http),
        )
        self.ctx = FakeContext(self.services)
        self.replies: list[str] = []

        async def fake_reply(update, text, kb=None, edit=False):
            self.replies.append(text)
            return SimpleNamespace(chat_id=1, message_id=1)

        for mod in (common, launch, trade, tracker, wallets, main):
            if hasattr(mod, "reply"):
                p = patch.object(mod, "reply", fake_reply)
                p.start()
                self.addCleanup(p.stop)

    async def asyncTearDown(self):
        await self.http.aclose()
        self.tmp.cleanup()


class KeystoreTests(unittest.TestCase):
    def test_roundtrip_and_formats(self):
        ks = Keystore(Fernet.generate_key().decode())
        kp = Keypair()
        self.assertEqual(ks.decrypt(ks.encrypt(kp)).pubkey(), kp.pubkey())
        self.assertNotIn(export_secret_key(kp), ks.encrypt(kp))
        self.assertEqual(parse_secret_key(export_secret_key(kp)).pubkey(), kp.pubkey())
        self.assertEqual(parse_secret_key(json.dumps(list(bytes(kp)))).pubkey(), kp.pubkey())
        with self.assertRaises(ValueError):
            parse_secret_key("not a key")

    def test_sign_versioned_fills_all_signatures(self):
        payer, mint = Keypair(), Keypair()
        signed = VersionedTransaction.from_bytes(sign_versioned(unsigned_tx(payer.pubkey(), [mint.pubkey()]), [mint, payer]))
        self.assertEqual(len(signed.signatures), 2)
        self.assertTrue(all(s != Signature.default() for s in signed.signatures))
        self.assertTrue(all(signed.verify_with_results()))


def make_image(w: int, h: int, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h)).save(buf, fmt)
    return buf.getvalue()


class ImageCheckTests(unittest.TestCase):
    def test_accepts_square_png_and_jpg(self):
        self.assertEqual(launch.check_image(make_image(512, 512)), "png")
        self.assertEqual(launch.check_image(make_image(1000, 1000, "JPEG")), "jpg")

    def test_rejects_bad_images(self):
        for raw, reason in (
            (make_image(800, 600), "square"),
            (make_image(256, 256), "at least 512px"),
            (make_image(600, 600, "GIF"), "PNG or JPG"),
            (b"not an image", "readable"),
        ):
            with self.assertRaisesRegex(ValueError, reason):
                launch.check_image(raw)


class FlowTests(TraderTestCase):
    async def test_import_wallet_deletes_key_message(self):
        kp = Keypair()
        upd = text_update("x")
        await wallets.start_import(upd, self.ctx)
        upd = text_update(export_secret_key(kp))
        await main.on_text(upd, self.ctx)
        upd.message.delete.assert_awaited()
        [w] = self.services.db.list_wallets(42)
        self.assertEqual(w.pubkey, str(kp.pubkey()))
        self.assertTrue(w.is_default)

    async def test_full_launch_flow(self):
        await wallets.create(text_update("x"), self.ctx)
        [w] = self.services.db.list_wallets(42)
        self.chain.balances[w.pubkey] = 2 * 10**9

        await launch.start(text_update("x"), self.ctx)
        self.assertIn("Token name", self.replies[-1])
        await main.on_text(text_update("x" * 33), self.ctx)
        self.assertIn("1-32", self.replies[-1])
        await main.on_text(text_update("My Token"), self.ctx)
        self.assertIn("Name set: My Token", self.replies[-1])
        self.assertIn("Enter <b>SYMBOL</b> (2-10, A-Z)", self.replies[-1])
        for bad in ("M", "MT1", "TOOLONGSYMBOL"):
            await main.on_text(text_update(bad), self.ctx)
            self.assertIn("letters A-Z", self.replies[-1])
        await main.on_text(text_update("$mtk"), self.ctx)
        self.assertIn("Symbol set: $MTK", self.replies[-1])
        self.assertIn("1-2 lines. Avoid links.", self.replies[-1])
        await main.on_text(text_update("A test token"), self.ctx)
        self.assertIn("Upload token image</b>\nPNG/JPG · Square · ≥512px", self.replies[-1])
        self.assertEqual(self.ctx.user_data["launch"]["symbol"], "MTK")

        # image step: simulate a received image
        self.ctx.user_data["launch"].update(image=b"img", image_name="a.png")
        common.set_awaiting(self.ctx, "launch_socials")
        await main.on_text(text_update("https://x.com/mtk https://t.me/mtk https://mtk.io"), self.ctx)
        data = self.ctx.user_data["launch"]
        self.assertEqual((data["twitter"], data["telegram"], data["website"]), ("https://x.com/mtk", "https://t.me/mtk", "https://mtk.io"))

        await main.on_text(text_update("5"), self.ctx)  # more than the wallet holds
        self.assertIn("needs about", self.replies[-1])
        await main.on_text(text_update("0.5"), self.ctx)
        self.assertIn("Confirm launch", self.replies[-1])

        await launch.confirm(text_update("x"), self.ctx)
        [payload] = self.chain.pumpportal
        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["amount"], 0.5)
        self.assertEqual(payload["tokenMetadata"]["uri"], "https://ipfs.example/meta.json")
        [raw] = self.chain.sent
        tx = VersionedTransaction.from_bytes(raw)
        self.assertTrue(all(tx.verify_with_results()))
        self.assertEqual(len(self.services.db.pending_txs()), 1)

    async def test_buy_checks_balance_then_submits(self):
        await wallets.create(text_update("x"), self.ctx)
        [w] = self.services.db.list_wallets(42)
        mint = str(Keypair().pubkey())
        await trade.buy(text_update("x"), self.ctx, mint, 1.0)
        self.assertIn("Not enough SOL", self.replies[-1])
        self.chain.balances[w.pubkey] = 3 * 10**9
        await trade.buy(text_update("x"), self.ctx, mint, 1.0)
        self.assertEqual(self.chain.pumpportal[-1]["action"], "buy")
        self.assertEqual(len(self.chain.sent), 1)

    async def test_tracker_notifies_on_confirm_and_failure(self):
        db = self.services.db
        db.track_tx("sigA", 42, 42, "buy", "Buy A")
        db.track_tx("sigB", 42, 42, "sell", "Sell B")
        self.chain.statuses = {"sigA": {"confirmationStatus": "confirmed", "err": None}, "sigB": {"err": {"x": 1}}}
        await tracker.poll(self.ctx)
        self.assertEqual(db.pending_txs(), [])
        self.assertEqual({t.status for t in db.recent_txs(42)}, {"confirmed", "failed"})
        self.assertEqual(self.ctx.bot.send_message.await_count, 2)

    async def test_withdraw_max_leaves_fee(self):
        await wallets.create(text_update("x"), self.ctx)
        [w] = self.services.db.list_wallets(42)
        self.chain.balances[w.pubkey] = 10**9
        dest = str(Keypair().pubkey())
        await wallets.start_withdraw(text_update("x"), self.ctx, w.id)
        await main.on_text(text_update(dest), self.ctx)
        await main.on_text(text_update("max"), self.ctx)
        [raw] = self.chain.sent
        tx = Transaction.from_bytes(raw)
        lamports = int.from_bytes(bytes(tx.message.instructions[0].data)[4:12], "little")
        self.assertEqual(lamports, 10**9 - 5000)


if __name__ == "__main__":
    unittest.main()
