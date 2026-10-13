import sqlite3
import time
from dataclasses import dataclass

from . import config


@dataclass
class Wallet:
    id: int
    user_id: int
    label: str
    pubkey: str
    enc_secret: str
    is_default: bool


@dataclass
class TrackedTx:
    signature: str
    user_id: int
    chat_id: int
    kind: str
    description: str
    status: str
    created_at: float


@dataclass
class Settings:
    slippage: float
    priority_fee: float


SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    pubkey TEXT NOT NULL,
    enc_secret TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, pubkey)
);
CREATE TABLE IF NOT EXISTS txs (
    signature TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER PRIMARY KEY,
    slippage REAL NOT NULL,
    priority_fee REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS launches (
    mint TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signature TEXT,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # wallets

    def add_wallet(self, user_id: int, label: str, pubkey: str, enc_secret: str) -> Wallet:
        has_default = self.default_wallet(user_id) is not None
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO wallets (user_id, label, pubkey, enc_secret, is_default) VALUES (?, ?, ?, ?, ?)",
                (user_id, label, pubkey, enc_secret, 0 if has_default else 1),
            )
        return self.get_wallet(user_id, cur.lastrowid)

    def list_wallets(self, user_id: int) -> list[Wallet]:
        rows = self.conn.execute("SELECT * FROM wallets WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
        return [self._wallet(r) for r in rows]

    def get_wallet(self, user_id: int, wallet_id: int) -> Wallet | None:
        row = self.conn.execute(
            "SELECT * FROM wallets WHERE user_id = ? AND id = ?", (user_id, wallet_id)
        ).fetchone()
        return self._wallet(row) if row else None

    def default_wallet(self, user_id: int) -> Wallet | None:
        row = self.conn.execute(
            "SELECT * FROM wallets WHERE user_id = ? ORDER BY is_default DESC, id LIMIT 1", (user_id,)
        ).fetchone()
        return self._wallet(row) if row else None

    def set_default_wallet(self, user_id: int, wallet_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE wallets SET is_default = (id = ?) WHERE user_id = ?", (wallet_id, user_id))

    def delete_wallet(self, user_id: int, wallet_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM wallets WHERE user_id = ? AND id = ?", (user_id, wallet_id))

    @staticmethod
    def _wallet(row) -> Wallet:
        return Wallet(row["id"], row["user_id"], row["label"], row["pubkey"], row["enc_secret"], bool(row["is_default"]))

    # tx tracker

    def track_tx(self, signature: str, user_id: int, chat_id: int, kind: str, description: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO txs (signature, user_id, chat_id, kind, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (signature, user_id, chat_id, kind, description, time.time()),
            )

    def pending_txs(self) -> list[TrackedTx]:
        rows = self.conn.execute("SELECT * FROM txs WHERE status = 'pending' ORDER BY created_at").fetchall()
        return [TrackedTx(**dict(r)) for r in rows]

    def recent_txs(self, user_id: int, limit: int = 10) -> list[TrackedTx]:
        rows = self.conn.execute(
            "SELECT * FROM txs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit)
        ).fetchall()
        return [TrackedTx(**dict(r)) for r in rows]

    def set_tx_status(self, signature: str, status: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE txs SET status = ? WHERE signature = ?", (status, signature))

    # settings

    def get_settings(self, user_id: int) -> Settings:
        row = self.conn.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return Settings(config.DEFAULT_SLIPPAGE, config.DEFAULT_PRIORITY_FEE)
        return Settings(row["slippage"], row["priority_fee"])

    def update_settings(self, user_id: int, **changes: float) -> Settings:
        s = self.get_settings(user_id)
        s.slippage = changes.get("slippage", s.slippage)
        s.priority_fee = changes.get("priority_fee", s.priority_fee)
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (user_id, slippage, priority_fee) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET slippage = excluded.slippage, priority_fee = excluded.priority_fee",
                (user_id, s.slippage, s.priority_fee),
            )
        return s

    # launches

    def record_launch(self, mint: str, user_id: int, name: str, symbol: str, signature: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO launches (mint, user_id, name, symbol, signature, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (mint, user_id, name, symbol, signature, time.time()),
            )
