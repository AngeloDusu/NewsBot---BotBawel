"""
bot/collectors/prices/base.py
-----------------------------
Kontrak dasar (interface) untuk semua penyedia data harga (`PriceProvider`)
serta fungsi normalisasi simbol supaya input user super fleksibel:
- "btc", "btcusd", "btc/usd", "btcusdt", "btc/usdt" -> ("BTC/USDT", "crypto")
- "xau", "xauusd", "xaa", "xaausd", "gold", "emas"   -> ("XAU/USD", "gold")
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
    price: str | float
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
    - "btc", "btcusd", "btc/usd", "btcusdt"        -> ("BTC/USDT", "crypto")
    - "xau", "xauusd", "xaausd" (typo), "gold"     -> ("XAU/USD", "gold")
    """
    cleaned = raw.upper().strip().replace("-", "/").replace(" ", "")

    # 1. Deteksi Emas / Gold (termasuk typo umum XAA / XAAUSD)
    gold_aliases = {
        "XAU", "XAUUSD", "XAU/USD", "XAUUSDT", "XAU/USDT",
        "XAA", "XAAUSD", "XAA/USD", "XAAUSDT", "XAA/USDT",  # Antisipasi typo
        "GOLD", "EMAS", "PAXG", "PAXGUSDT", "PAXG/USDT"
    }
    if cleaned in gold_aliases:
        return "XAU/USD", "gold"

    # 2. Jika user pakai garis miring (mis. BTC/USD atau BTC/USDT)
    if "/" in cleaned:
        base, quote = cleaned.split("/", 1)
        if quote in {"USD", "USDT", "BUSD", "USDC"}:
            return f"{base}/USDT", "crypto"
        return f"{base}/{quote}", "crypto"

    # 3. Jika diakhiri USDT (mis. BTCUSDT -> BTC/USDT)
    if cleaned.endswith("USDT") and len(cleaned) > 4:
        base = cleaned[:-4]
        return f"{base}/USDT", "crypto"

    # 4. Jika diakhiri USD (mis. BTCUSD -> BTC/USDT, ETHUSD -> ETH/USDT)
    if cleaned.endswith("USD") and len(cleaned) > 3:
        base = cleaned[:-3]
        return f"{base}/USDT", "crypto"

    # 5. Default: anggap kode koin saja (mis. BTC -> BTC/USDT, SOL -> SOL/USDT)
    return f"{cleaned}/USDT", "crypto"
