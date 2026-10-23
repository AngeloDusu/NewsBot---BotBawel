"""
bot/collectors/prices/crypto_ccxt.py
------------------------------------
Mengambil data harga dan candlestick crypto dari Binance Public API menggunakan `ccxt.async_support`.
100% gratis dan tidak membutuhkan API key.
"""

from __future__ import annotations

from datetime import datetime, timezone

import ccxt.async_support as ccxt

from bot.collectors.prices.base import CandleData, PriceProvider, TickerData


class CryptoCCXTProvider(PriceProvider):
    """Provider harga Crypto berbasis CCXT (Binance Spot)."""

    def __init__(self) -> None:
        self._exchange = ccxt.binance({"enableRateLimit": True})

    async def close(self) -> None:
        await self._exchange.close()

    async def fetch_ticker(self, symbol: str) -> TickerData:
        t = await self._exchange.fetch_ticker(symbol)
        ts_ms = t.get("timestamp")
        ts = (
            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if ts_ms
            else datetime.now(timezone.utc)
        )
        return TickerData(
            symbol=symbol,
            market="crypto",
            price=float(t.get("last") or t.get("close") or 0.0),
            change_24h_pct=float(t.get("percentage") or 0.0),
            high_24h=float(t.get("high") or 0.0),
            low_24h=float(t.get("low") or 0.0),
            volume_24h=float(t.get("quoteVolume") or t.get("baseVolume") or 0.0),
            timestamp=ts,
            source="Binance",
        )

    async def fetch_candles(
        self, symbol: str, timeframe: str = "30m", limit: int = 100
    ) -> list[CandleData]:
        ohlcv = await self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        candles: list[CandleData] = []
        for row in ohlcv:
            open_time = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            candles.append(
                CandleData(
                    open_time=open_time,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        return candles
