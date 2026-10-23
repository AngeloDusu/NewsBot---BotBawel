"""
bot/collectors/prices/router.py
-------------------------------
Pintu masuk tunggal (router) untuk semua permintaan harga & candlestick,
plus fungsi untuk menyimpan candlestick ke tabel `candles` di PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.collectors.prices.base import CandleData, TickerData, normalize_symbol
from bot.collectors.prices.crypto_ccxt import CryptoCCXTProvider
from bot.collectors.prices.gold import GoldPriceProvider
from bot.db.models import Candle
from bot.db.session import get_session


class MarketPriceRouter:
    """Memilih provider yang tepat (Crypto vs Gold) berdasarkan simbol."""

    def __init__(self, twelvedata_api_key: str | None = None) -> None:
        self.crypto = CryptoCCXTProvider()
        self.gold = GoldPriceProvider(api_key=twelvedata_api_key, fallback_crypto=self.crypto)

    async def close(self) -> None:
        await self.crypto.close()

    async def get_ticker(self, raw_symbol: str) -> TickerData:
        symbol, market = normalize_symbol(raw_symbol)
        if market == "gold":
            return await self.gold.fetch_ticker(symbol)
        return await self.crypto.fetch_ticker(symbol)

    async def get_candles(
        self, raw_symbol: str, timeframe: str = "30m", limit: int = 100
    ) -> tuple[str, str, list[CandleData]]:
        symbol, market = normalize_symbol(raw_symbol)
        if market == "gold":
            candles = await self.gold.fetch_candles(symbol, timeframe=timeframe, limit=limit)
        else:
            candles = await self.crypto.fetch_candles(symbol, timeframe=timeframe, limit=limit)

        await self._cache_candles(symbol, timeframe, candles)
        return symbol, market, candles

    async def _cache_candles(
        self, symbol: str, timeframe: str, candles: list[CandleData]
    ) -> None:
        """Simpan candle ke PostgreSQL (upsert: update jika sudah ada)."""
        if not candles:
            return
        try:
            async with get_session() as session:
                rows = [
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "open_time": c.open_time,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles[-30:]  # simpan 30 candle terakhir agar hemat & cepat
                ]
                stmt = pg_insert(Candle).values(rows)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_candle_sym_tf_time",
                    set_={
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            # Jangan gagalkan fitur utama bila gagal menulis cache
            pass
