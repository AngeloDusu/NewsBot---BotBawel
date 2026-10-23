"""
bot/collectors/prices/base.py
-----------------------------
Kontrak dasar (interface) untuk semua penyedia data harga (`PriceProvider`)
serta fungsi normalisasi simbol supaya input user fleksibel:
- "btc", "btcusdt", "btc/usdt" -> ("BTC/USDT", "crypto")
- "xau", "xauusd", "gold"      -> ("XAU/USD", "gold")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TickerData:
    """Data harga saat ini (snapshot 24 jam)."""
    symbol: str
    market: str
    price: float
    change_24h_pct: float
    high_24h: float
    low_24h: float
    volume_24h: float
    timestamp: datetime
    source: str


@dataclass
class CandleData:
    """Satu batang candlestick (OHLCV)."""
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceProvider(ABC):
    """Interface standar yang wajib diikuti setiap provider market."""

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> TickerData:
        """Ambil harga terbaru beserta perubahan 24 jam."""

    @abstractmethod
    async def fetch_candles(
        self, symbol: str, timeframe: str = "30m", limit: int = 100
    ) -> list[CandleData]:
        """Ambil daftar candlestick historis untuk perhitungan indikator."""


def normalize_symbol(raw: str) -> tuple[str, str]:
    """
    Ubah input simbol bebas dari user menjadi (symbol_standar, market).
    Contoh:
    - "btc"      -> ("BTC/USDT", "crypto")
    - "ethusdt"  -> ("ETH/USDT", "crypto")
    - "xauusd"   -> ("XAU/USD", "gold")
    - "gold"     -> ("XAU/USD", "gold")
    """
    cleaned = raw.upper().strip().replace("-", "/")

    if cleaned in {"XAU", "XAUUSD", "XAU/USD", "GOLD"}:
        return "XAU/USD", "gold"

    if "/" in cleaned:
        return cleaned, "crypto"

    if cleaned.endswith("USDT") and len(cleaned) > 4:
        base = cleaned[:-4]
        return f"{base}/USDT", "crypto"

    return f"{cleaned}/USDT", "crypto"
