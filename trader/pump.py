"""pump.fun launch/trade via PumpPortal's local-transaction API.

PumpPortal builds the unsigned transaction; we sign it locally so secret keys never leave the bot.
"""
from dataclasses import dataclass

import httpx

from . import config


class PumpError(Exception):
    pass


@dataclass
class TokenMeta:
    name: str
    symbol: str
    description: str = ""
    twitter: str = ""
    telegram: str = ""
    website: str = ""


class PumpClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def upload_metadata(self, meta: TokenMeta, image: bytes, filename: str) -> str:
        form = {
            "name": meta.name,
            "symbol": meta.symbol,
            "description": meta.description,
            "twitter": meta.twitter,
            "telegram": meta.telegram,
            "website": meta.website,
            "showName": "true",
        }
        resp = await self.http.post(
            config.PUMP_IPFS_URL, data=form, files={"file": (filename, image)}, timeout=60
        )
        if resp.status_code != 200:
            raise PumpError(f"Metadata upload failed ({resp.status_code})")
        uri = resp.json().get("metadataUri")
        if not uri:
            raise PumpError("Metadata upload returned no URI")
        return uri

    async def _build(self, payload: dict) -> bytes:
        resp = await self.http.post(config.PUMPPORTAL_TRADE_URL, json=payload, timeout=30)
        if resp.status_code != 200:
            raise PumpError(f"Could not build transaction: {resp.text[:200] or resp.status_code}")
        return resp.content

    async def build_create(
        self, creator: str, mint: str, meta: TokenMeta, uri: str, dev_buy_sol: float, slippage: float, priority_fee: float
    ) -> bytes:
        return await self._build(
            {
                "publicKey": creator,
                "action": "create",
                "tokenMetadata": {"name": meta.name, "symbol": meta.symbol, "uri": uri},
                "mint": mint,
                "denominatedInSol": "true",
                "amount": dev_buy_sol,
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": "pump",
            }
        )

    async def build_buy(self, wallet: str, mint: str, sol: float, slippage: float, priority_fee: float) -> bytes:
        return await self._build(
            {
                "publicKey": wallet,
                "action": "buy",
                "mint": mint,
                "denominatedInSol": "true",
                "amount": sol,
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": "auto",
            }
        )

    async def build_sell(self, wallet: str, mint: str, percent: int, slippage: float, priority_fee: float) -> bytes:
        return await self._build(
            {
                "publicKey": wallet,
                "action": "sell",
                "mint": mint,
                "denominatedInSol": "false",
                "amount": f"{percent}%",
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": "auto",
            }
        )
