import base64
from dataclasses import dataclass

import httpx
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction, VersionedTransaction

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
TX_FEE_LAMPORTS = 5000


class RpcError(Exception):
    pass


@dataclass
class TokenHolding:
    mint: str
    amount: float
    decimals: int


@dataclass
class MintInfo:
    mint: str
    decimals: int
    supply: float
    mint_authority: str | None
    freeze_authority: str | None


def is_pubkey(text: str) -> bool:
    try:
        Pubkey.from_string(text.strip())
        return True
    except Exception:
        return False


class SolanaRpc:
    def __init__(self, url: str, http: httpx.AsyncClient):
        self.url = url
        self.http = http

    async def call(self, method: str, params: list):
        resp = await self.http.post(
            self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RpcError(data["error"].get("message", str(data["error"])))
        return data["result"]

    async def balance_sol(self, pubkey: str) -> float:
        result = await self.call("getBalance", [pubkey, {"commitment": "confirmed"}])
        return result["value"] / LAMPORTS_PER_SOL

    async def token_holdings(self, owner: str) -> list[TokenHolding]:
        holdings: dict[str, TokenHolding] = {}
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            result = await self.call(
                "getTokenAccountsByOwner",
                [owner, {"programId": program}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            )
            for acc in result["value"]:
                info = acc["account"]["data"]["parsed"]["info"]
                amount = info["tokenAmount"]
                ui = float(amount.get("uiAmountString") or 0)
                if ui <= 0:
                    continue
                prev = holdings.get(info["mint"])
                holdings[info["mint"]] = TokenHolding(
                    info["mint"], ui + (prev.amount if prev else 0), int(amount["decimals"])
                )
        return list(holdings.values())

    async def mint_info(self, mint: str) -> MintInfo | None:
        result = await self.call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        value = result["value"]
        if not value or not isinstance(value["data"], dict) or value["data"].get("parsed", {}).get("type") != "mint":
            return None
        info = value["data"]["parsed"]["info"]
        decimals = int(info["decimals"])
        return MintInfo(
            mint=mint,
            decimals=decimals,
            supply=int(info["supply"]) / 10**decimals,
            mint_authority=info.get("mintAuthority"),
            freeze_authority=info.get("freezeAuthority"),
        )

    async def largest_holders(self, mint: str) -> list[tuple[str, float]]:
        result = await self.call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
        return [(a["address"], float(a.get("uiAmountString") or 0)) for a in result["value"]]

    async def latest_blockhash(self) -> Hash:
        result = await self.call("getLatestBlockhash", [{"commitment": "confirmed"}])
        return Hash.from_string(result["value"]["blockhash"])

    async def send_raw(self, raw: bytes) -> str:
        return await self.call(
            "sendTransaction",
            [
                base64.b64encode(raw).decode(),
                {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 3},
            ],
        )

    async def signature_statuses(self, signatures: list[str]) -> list[dict | None]:
        result = await self.call("getSignatureStatuses", [signatures, {"searchTransactionHistory": True}])
        return result["value"]

    async def transfer_sol(self, sender: Keypair, to: str, lamports: int) -> str:
        ix = transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=Pubkey.from_string(to), lamports=lamports))
        blockhash = await self.latest_blockhash()
        msg = Message.new_with_blockhash([ix], sender.pubkey(), blockhash)
        tx = Transaction([sender], msg, blockhash)
        return await self.send_raw(bytes(tx))


def sign_versioned(raw: bytes, signers: list[Keypair]) -> bytes:
    """Sign an unsigned serialized v0 transaction (as returned by PumpPortal)."""
    unsigned = VersionedTransaction.from_bytes(raw)
    return bytes(VersionedTransaction(unsigned.message, signers))
