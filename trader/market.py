from dataclasses import dataclass

import httpx

from . import config

SOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class Coin:
    mint: str
    name: str
    symbol: str
    market_cap_usd: float | None


class MarketClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _coins(self, sort: str, limit: int) -> list[Coin]:
        resp = await self.http.get(
            config.PUMP_COINS_URL,
            params={"offset": 0, "limit": limit, "sort": sort, "order": "DESC", "includeNsfw": "false"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("coins", []) if isinstance(data, dict) else data
        return [
            Coin(c["mint"], c.get("name", "?"), c.get("symbol", "?"), c.get("usd_market_cap"))
            for c in items
            if c.get("mint")
        ]

    async def latest(self, limit: int = 10) -> list[Coin]:
        return await self._coins("created_timestamp", limit)

    async def hot(self, limit: int = 10) -> list[Coin]:
        return await self._coins("market_cap", limit)

    async def prices_usd(self, mints: list[str]) -> dict[str, float]:
        """USD prices from Jupiter. Missing or failed lookups are left out of the result."""
        prices: dict[str, float] = {}
        for i in range(0, len(mints), 50):
            chunk = mints[i : i + 50]
            try:
                resp = await self.http.get(config.JUPITER_PRICE_URL, params={"ids": ",".join(chunk)}, timeout=15)
                resp.raise_for_status()
                for mint, info in (resp.json() or {}).items():
                    price = (info or {}).get("usdPrice")
                    if price is not None:
                        prices[mint] = float(price)
            except (httpx.HTTPError, ValueError):
                continue
        return prices
