"""
bot/collectors/prices/crypto_ccxt.py
------------------------------------
Provider harga & candlestick Crypto dengan **Multi-Domain Fallback** gratis tanpa API key
yang tahan terhadap blokir ISP Indonesia (IndiHome, Telkomsel, Biznet, dll):

Urutan Domain Otomatis:
1. `https://data-api.binance.vision/api/v3` (Server resmi market data publik Binance Vision)
2. `https://api-gcp.binance.com/api/v3`     (Mirror Google Cloud Binance)
3. `https://min-api.cryptocompare.com`      (CryptoCompare Public API - bebas blokir ISP)
4. `https://api.kraken.com`                 (Kraken Public API)
5. `https://query1.finance.yahoo.com`       (Yahoo Finance API - 100% bebas blokir di semua ISP)
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from loguru import logger

from bot.collectors.prices.base import CandleData, PriceProvider, TickerData

BINANCE_MIRRORS = [
    ("Binance Vision", "https://data-api.binance.vision/api/v3"),
    ("Binance GCP", "https://api-gcp.binance.com/api/v3"),
    ("Binance Mirror 1", "https://api1.binance.com/api/v3"),
]


class CryptoCCXTProvider(PriceProvider):
    """Provider Crypto Multi-Domain (Binance Mirrors -> CryptoCompare -> Kraken -> Yahoo Finance)."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BotBawel/1.0"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            return base.upper(), quote.upper()
        return symbol.upper(), "USDT"

    async def fetch_ticker(self, symbol: str) -> TickerData:
        base, quote = self._split_symbol(symbol)
        pair = f"{base}{quote}"

        # 1. Coba deretan mirror resmi Binance
        for source_name, base_url in BINANCE_MIRRORS:
            try:
                resp = await self._http.get(f"{base_url}/ticker/24hr", params={"symbol": pair})
                if resp.status_code == 200:
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
                        source=source_name,
                    )
            except Exception as e:
                logger.debug(f"{source_name} ticker gagal untuk {pair}: {e}")

        # 2. Fallback: CryptoCompare Public API (Bebas blokir ISP Indonesia)
        try:
            resp = await self._http.get(
                "https://min-api.cryptocompare.com/data/pricemultifull",
                params={"fsyms": base, "tsyms": "USD"},
            )
            if resp.status_code == 200:
                raw = resp.json().get("RAW", {}).get(base, {}).get("USD")
                if raw:
                    return TickerData(
                        symbol=symbol,
                        market="crypto",
                        price=float(raw["PRICE"]),
                        change_24h_pct=float(raw.get("CHANGEPCT24HOUR") or 0.0),
                        high_24h=float(raw.get("HIGH24HOUR") or raw["PRICE"]),
                        low_24h=float(raw.get("LOW24HOUR") or raw["PRICE"]),
                        volume_24h=float(raw.get("TOTALVOLUME24HTO") or 0.0),
                        timestamp=datetime.now(timezone.utc),
                        source="CryptoCompare",
                    )
        except Exception as e:
            logger.debug(f"CryptoCompare ticker gagal untuk {base}: {e}")

        # 3. Fallback: Yahoo Finance Chart Meta (100% bebas blokir ISP)
        yf_sym = "GC=F" if base == "PAXG" else f"{base}-USD"
        resp = await self._http.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}",
            params={"interval": "15m", "range": "2d"},
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        meta = result["meta"]
        price = float(meta["regularMarketPrice"])
        prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
        pct = ((price - prev) / prev * 100.0) if prev else 0.0
        q = result["indicators"]["quote"][0]
        highs = [h for h in (q.get("high") or []) if h is not None]
        lows = [l for l in (q.get("low") or []) if l is not None]
        return TickerData(
            symbol=symbol,
            market="crypto",
            price=price,
            change_24h_pct=pct,
            high_24h=float(max(highs)) if highs else price,
            low_24h=float(min(lows)) if lows else price,
            volume_24h=0.0,
            timestamp=datetime.now(timezone.utc),
            source="Yahoo Finance",
        )

    async def fetch_candles(
        self, symbol: str, timeframe: str = "30m", limit: int = 100
    ) -> list[CandleData]:
        base, quote = self._split_symbol(symbol)
        pair = f"{base}{quote}"

        # 1. Coba deretan mirror resmi Binance
        for source_name, base_url in BINANCE_MIRRORS:
            try:
                resp = await self._http.get(
                    f"{base_url}/klines",
                    params={"symbol": pair, "interval": timeframe, "limit": limit},
                )
                if resp.status_code == 200:
                    raw_klines = resp.json()
                    if raw_klines:
                        return [
                            CandleData(
                                open_time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=float(row[5]),
                            )
                            for row in raw_klines
                        ]
            except Exception as e:
                logger.debug(f"{source_name} candles gagal untuk {pair}: {e}")

        # 2. Fallback: CryptoCompare Public Histominute / Histohour
        try:
            if timeframe == "1h":
                endpoint = "https://min-api.cryptocompare.com/data/v2/histohour"
                params = {"fsym": base, "tsym": "USD", "limit": limit}
            else:
                agg = 15 if timeframe == "15m" else 30
                endpoint = "https://min-api.cryptocompare.com/data/v2/histominute"
                params = {"fsym": base, "tsym": "USD", "limit": limit, "aggregate": agg}

            resp = await self._http.get(endpoint, params=params)
            if resp.status_code == 200:
                rows = resp.json().get("Data", {}).get("Data", [])
                if rows:
                    return [
                        CandleData(
                            open_time=datetime.fromtimestamp(r["time"], tz=timezone.utc),
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                            volume=float(r.get("volumeto") or 0.0),
                        )
                        for r in rows
                        if r.get("close")
                    ]
        except Exception as e:
            logger.debug(f"CryptoCompare candles gagal untuk {base}: {e}")

        # 3. Fallback: Yahoo Finance Chart API (15m / 30m / 1h)
        yf_sym = "GC=F" if base == "PAXG" else f"{base}-USD"
        yf_interval = {"15m": "15m", "30m": "30m", "1h": "60m"}.get(timeframe, "30m")
        resp = await self._http.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}",
            params={"interval": yf_interval, "range": "5d"},
        )
        resp.raise_for_status()
        res = resp.json()["chart"]["result"][0]
        timestamps = res["timestamp"]
        q = res["indicators"]["quote"][0]
        candles: list[CandleData] = []
        for idx, ts_sec in enumerate(timestamps):
            o, h, l, c = q["open"][idx], q["high"][idx], q["low"][idx], q["close"][idx]
            if None in (o, h, l, c):
                continue
            v = q["volume"][idx] if q.get("volume") and q["volume"][idx] is not None else 0.0
            candles.append(
                CandleData(
                    open_time=datetime.fromtimestamp(ts_sec, tz=timezone.utc),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=float(v),
                )
            )
        return candles[-limit:]
