"""
bot/services/technical.py
-------------------------
Mesin Analisis Teknikal & Multi-Timeframe Signal Scanner (15m, 30m, 1h)
yang mereplikasi setup TradingView kamu:
- EMA Cross 5 / 20 (bisa diganti SMA lewat config.yaml)
- RSI 14 (Wilder smoothing) + garis MA dari RSI (SMA 14)
- Support & Resistance otomatis (swing low & swing high) + arah channel (regresi linear)
- Rating Sinyal Konfluensi ⭐ sampai ⭐⭐⭐
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.collectors.prices.base import CandleData
from bot.config import IndicatorConfig


@dataclass
class TimeframeAnalysis:
    """Hasil perhitungan indikator pada satu timeframe."""
    symbol: str
    timeframe: str
    last_price: float
    ma_fast_val: float
    ma_slow_val: float
    prev_ma_fast: float
    prev_ma_slow: float
    rsi_val: float
    rsi_ma_val: float
    support: float
    resistance: float
    channel_slope: str        # "Naik (Ascending)", "Turun (Descending)", "Mendatar (Sideways)"
    trend_bias: str           # "Bullish" atau "Bearish"
    cross_event: str | None   # "BULLISH_CROSS", "BEARISH_CROSS", atau None
    rsi_warning: str | None   # Peringatan Overbought / Oversold


@dataclass
class ConfluenceSignal:
    """Hasil akhir konfluensi 3 timeframe (15m, 30m, 1h)."""
    symbol: str
    direction: str            # "Bullish", "Bearish", atau "Netral"
    stars: int                # 0 - 3 bintang
    trigger_reason: str
    tf_30m: TimeframeAnalysis
    tf_15m: TimeframeAnalysis | None = None
    tf_1h: TimeframeAnalysis | None = None


def _compute_ma(series: pd.Series, length: int, ma_type: str = "ema") -> pd.Series:
    if ma_type.lower() == "sma":
        return series.rolling(window=length).mean()
    return series.ewm(span=length, adjust=False).mean()


def _compute_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Hitung RSI dengan metode Wilder's Smoothing (identik dengan TradingView)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def analyze_candles(
    symbol: str,
    timeframe: str,
    candles: list[CandleData],
    cfg: IndicatorConfig,
) -> TimeframeAnalysis:
    """Hitung seluruh indikator teknikal untuk satu daftar candlestick."""
    df = pd.DataFrame(
        [
            {
                "open_time": c.open_time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    )

    df["ma_fast"] = _compute_ma(df["close"], cfg.ma_fast, cfg.ma_type)
    df["ma_slow"] = _compute_ma(df["close"], cfg.ma_slow, cfg.ma_type)
    df["rsi"] = _compute_rsi(df["close"], cfg.rsi_length)
    df["rsi_ma"] = df["rsi"].rolling(window=cfg.rsi_ma_length).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    ma_fast_val = float(last["ma_fast"])
    ma_slow_val = float(last["ma_slow"])
    prev_fast = float(prev["ma_fast"])
    prev_slow = float(prev["ma_slow"])

    # Deteksi perpotongan EMA 5 dan EMA 20 pada 2 candle terakhir
    cross_event: str | None = None
    if prev_fast <= prev_slow and ma_fast_val > ma_slow_val:
        cross_event = "BULLISH_CROSS"
    elif prev_fast >= prev_slow and ma_fast_val < ma_slow_val:
        cross_event = "BEARISH_CROSS"

    trend_bias = "Bullish" if ma_fast_val >= ma_slow_val else "Bearish"

    rsi_val = float(last["rsi"])
    rsi_ma_val = float(last["rsi_ma"]) if not np.isnan(last["rsi_ma"]) else rsi_val

    rsi_warning: str | None = None
    if rsi_val >= cfg.rsi_overbought:
        rsi_warning = f"Rawan Overbought (RSI {rsi_val:.1f} >= {cfg.rsi_overbought:.0f})"
    elif rsi_val <= cfg.rsi_oversold:
        rsi_warning = f"Rawan Oversold (RSI {rsi_val:.1f} <= {cfg.rsi_oversold:.0f})"

    # Support & Resistance dari 30 candle terakhir
    recent = df.tail(30)
    support = float(recent["low"].min())
    resistance = float(recent["high"].max())

    # Kemiringan channel dengan regresi linear sederhana pada harga penutupan
    y = recent["close"].to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    slope_pct = 0.0
    if len(y) >= 5 and y[0] != 0:
        slope = float(np.polyfit(x, y, 1)[0])
        slope_pct = (slope * len(y)) / y[0] * 100.0

    if slope_pct > 0.35:
        channel_slope = f"Naik / Ascending ({slope_pct:+.2f}%)"
    elif slope_pct < -0.35:
        channel_slope = f"Turun / Descending ({slope_pct:+.2f}%)"
    else:
        channel_slope = f"Mendatar / Sideways ({slope_pct:+.2f}%)"

    return TimeframeAnalysis(
        symbol=symbol,
        timeframe=timeframe,
        last_price=float(last["close"]),
        ma_fast_val=ma_fast_val,
        ma_slow_val=ma_slow_val,
        prev_ma_fast=prev_fast,
        prev_ma_slow=prev_slow,
        rsi_val=rsi_val,
        rsi_ma_val=rsi_ma_val,
        support=support,
        resistance=resistance,
        channel_slope=channel_slope,
        trend_bias=trend_bias,
        cross_event=cross_event,
        rsi_warning=rsi_warning,
    )


def evaluate_confluence(
    tf_15m: TimeframeAnalysis,
    tf_30m: TimeframeAnalysis,
    tf_1h: TimeframeAnalysis,
    require_fresh_cross: bool = False,
) -> ConfluenceSignal:
    """
    Evaluasi konfluensi multi-timeframe sesuai aturan di docs/plan.md:
    - Trigger utama di 30m (EMA 5 vs EMA 20)
    - Konfirmasi RSI 14 vs MA RSI & level 50 di 30m
    - Filter tren di 1h (harga terhadap EMA 20) + timing di 15m (EMA 5 vs EMA 20)
    """
    if require_fresh_cross and tf_30m.cross_event is None:
        return ConfluenceSignal(
            symbol=tf_30m.symbol,
            direction="Netral",
            stars=0,
            trigger_reason="Belum ada EMA 5/20 cross baru di 30m",
            tf_30m=tf_30m,
            tf_15m=tf_15m,
            tf_1h=tf_1h,
        )

    direction = tf_30m.trend_bias
    stars = 1  # Bintang 1: arah/cross EMA 5/20 di 30m

    if direction == "Bullish":
        rsi_ok = tf_30m.rsi_val > tf_30m.rsi_ma_val and tf_30m.rsi_val > 50.0
        htf_ok = tf_1h.last_price > tf_1h.ma_slow_val and tf_15m.ma_fast_val > tf_15m.ma_slow_val
    else:
        rsi_ok = tf_30m.rsi_val < tf_30m.rsi_ma_val and tf_30m.rsi_val < 50.0
        htf_ok = tf_1h.last_price < tf_1h.ma_slow_val and tf_15m.ma_fast_val < tf_15m.ma_slow_val

    if rsi_ok:
        stars += 1
    if rsi_ok and htf_ok:
        stars += 1

    if tf_30m.cross_event == "BULLISH_CROSS":
        reason = "EMA 5 baru saja Golden Cross ke atas EMA 20 di 30m"
    elif tf_30m.cross_event == "BEARISH_CROSS":
        reason = "EMA 5 baru saja Death Cross ke bawah EMA 20 di 30m"
    else:
        reason = f"EMA 5 berada di {'atas' if direction == 'Bullish' else 'bawah'} EMA 20 pada 30m"

    return ConfluenceSignal(
        symbol=tf_30m.symbol,
        direction=direction,
        stars=stars,
        trigger_reason=reason,
        tf_30m=tf_30m,
        tf_15m=tf_15m,
        tf_1h=tf_1h,
    )
