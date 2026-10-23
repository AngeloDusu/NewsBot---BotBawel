"""
bot/collectors/prices/gold.py
-----------------------------
Provider harga Emas (XAU/USD) dengan **Multi-Domain Fallback**:
1. Jika `TWELVEDATA_API_KEY` diisi di `.env`, ambil `XAU/USD` dari Twelve Data API.
2. Fallback ke `PAXG/USDT` (PAX Gold 1:1 troy oz) lewat rantai mirror di `CryptoCCXTProvider`
   (Binance Vision -> Binance GCP -> CryptoCompare -> Yahoo Finance `GC=F`).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from loguru import logger

from bot.collectors.prices.base import CandleData, PriceProvider, TickerData
from bot.collectors.prices.crypto_ccxt import CryptoCCXTProvider

_TF_MAP = {
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
}


class GoldPriceProvider(PriceProvider):
    """Provider XAU/USD dengan Twelve Data + multi-domain fallback."""

    def __init__(self, api_key: str | None, fallback_crypto: CryptoCCXTProvider) -> None:
        self._api_key = api_key
        self._fallback = fallback_crypto

    async def fetch_ticker(self, symbol: str = "XAU/USD") -> TickerData:
        if self._api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.twelvedata.com/quote",
                        params={"symbol": "XAU/USD", "apikey": self._api_key},
                    )
                    data = resp.json()
                    if "close" in data:
                        return TickerData(
                            symbol="XAU/USD",
                            market="gold",
                            price=float(data["close"]),
                            change_24h_pct=float(data.get("percent_change") or 0.0),
                            high_24h=float(data.get("high") or data["close"]),
                            low_24h=float(data.get("low") or data["close"]),
                            volume_24h=0.0,
                            timestamp=datetime.now(timezone.utc),
                            source="TwelveData (XAU/USD)",
                        )
            except Exception as e:
                logger.warning(f"TwelveData XAU/USD gagal ({e}), fallback ke multi-domain")

        t = await self._fallback.fetch_ticker("PAXG/USDT")
        return TickerData(
            symbol="XAU/USD",
            market="gold",
            price=t.price,
            change_24h_pct=t.change_24h_pct,
            high_24h=t.high_24h,
            low_24h=t.low_24h,
            volume_24h=t.volume_24h,
            timestamp=t.timestamp,
            source=f"Gold Proxy ({t.source})",
        )

    async def fetch_candles(
        self, symbol: str = "XAU/USD", timeframe: str = "30m", limit: int = 100
    ) -> list[CandleData]:
        if self._api_key:
            interval = _TF_MAP.get(timeframe, "30min")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.twelvedata.com/time_series",
                        params={
                            "symbol": "XAU/USD",
                            "interval": interval,
                            "outputsize": limit,
                            "apikey": self._api_key,
                        },
                    )
                    data = resp.json()
                    values = data.get("values")
                    if values:
                        candles: list[CandleData] = []
                        for row in reversed(values):
                            dt = datetime.fromisoformat(row["datetime"]).replace(
                                tzinfo=timezone.utc
                            )
                            candles.append(
                                CandleData(
                                    open_time=dt,
                                    open=float(row["open"]),
                                    high=float(row["high"]),
                                    low=float(row["low"]),
                                    close=float(row["close"]),
                                    volume=float(row.get("volume") or 0.0),
                                )
                            )
                        return candles
            except Exception as e:
                logger.warning(f"TwelveData candles gagal ({e}), fallback ke multi-domain")

        return await self._fallback.fetch_candles("PAXG/USDT", timeframe=timeframe, limit=limit)
