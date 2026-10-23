"""
bot/collectors/prices/crypto_ccxt.py
------------------------------------
Mengambil data harga dan candlestick crypto secara gratis tanpa API key.

Catatan Penting (ISP Indonesia):
Domain utama `api.binance.com` sering diblokir oleh ISP di Indonesia (IndiHome/Telkomsel/dll).
Karena itu provider ini menggunakan:
1. Endpoint resmi Binance Market Data Vision (`https://data-api.binance.vision/api/v3`)
   yang TIDAK diblokir ISP Indonesia dan datanya 100% identik dengan Binance Spot!
2. Jika endpoint utama mengalami gangguan, otomatis fallback ke CCXT KuCoin / Gate.io.
"""

from __future__ import annotations

from datetime import datetime, timezone

import ccxt.async_support as ccxt
import httpx
from loguru import logger

from bot.collectors.prices.base import CandleData, PriceProvider, TickerData

# Endpoint resmi market data publik Binance (bebas blokir ISP Indonesia)
BINANCE_VISION_BASE = "https://data-api.binance.vision/api/v3"


class CryptoCCXTProvider(PriceProvider):
    """Provider harga Crypto (Binance Vision Direct + Fallback CCXT KuCoin)."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=12.0)
        self._fallback_exchange = ccxt.kucoin({"enableRateLimit": True})

    async def close(self) -> None:
        await self._http.aclose()
        await self._fallback_exchange.close()

    @staticmethod
    def _to_binance_pair(symbol: str) -> str:
        """Ubah 'BTC/USDT' menjadi 'BTCUSDT' untuk REST API Binance Vision."""
        return symbol.replace("/", "").replace("-", "").upper()

    async def fetch_ticker(self, symbol: str) -> TickerData:
        pair = self._to_binance_pair(symbol)
        try:
            resp = await self._http.get(
                f"{BINANCE_VISION_BASE}/ticker/24hr",
                params={"symbol": pair},
            )
            resp.raise_for_status()
            d = resp.json()
            close_time = d.get("closeTime")
            ts = (
                datetime.fromtimestamp(close_time / 1000, tz=timezone.utc)
                if close_time
                else datetime.now(timezone.utc)
            )
            return TickerData(
                symbol=symbol,
                market="crypto",
                price=float(d["lastPrice"]),
                change_24h_pct=float(d["priceChangePercent"]),
                high_24h=float(d["highPrice"]),
                low_24h=float(d["lowPrice"]),
                volume_24h=float(d["quoteVolume"]),
                timestamp=ts,
                source="Binance (data-api.binance.vision)",
            )
        except Exception as e:
            logger.warning(f"Binance Vision ticker gagal untuk {symbol} ({e}), fallback ke KuCoin")

        t = await self._fallback_exchange.fetch_ticker(symbol)
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
            source="KuCoin (Fallback)",
        )

    async def fetch_candles(
        self, symbol: str, timeframe: str = "30m", limit: int = 100
    ) -> list[CandleData]:
        pair = self._to_binance_pair(symbol)
        try:
            resp = await self._http.get(
                f"{BINANCE_VISION_BASE}/klines",
                params={"symbol": pair, "interval": timeframe, "limit": limit},
            )
            resp.raise_for_status()
            raw_klines = resp.json()
            candles: list[CandleData] = []
            for row in raw_klines:
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
        except Exception as e:
            logger.warning(f"Binance Vision candles gagal untuk {symbol} ({e}), fallback ke KuCoin")

        ohlcv = await self._fallback_exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            CandleData(
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in ohlcv
        ]
