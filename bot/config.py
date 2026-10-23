"""
bot/config.py
-------------
Memuat seluruh konfigurasi aplikasi dari dua sumber:
1. File `.env`      -> data rahasia (token Discord, API key, URL database)
2. File `config.yaml` -> pengaturan perilaku bot (watchlist, indikator, jadwal, channel ID)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

# Direktori paling atas project (NewsBot - BotBawel/)
ROOT_DIR = Path(__file__).resolve().parent.parent

# Muat isi file .env ke environment variables OS
load_dotenv(ROOT_DIR / ".env")


def _require_env(name: str) -> str:
    """Ambil env var wajib. Kalau kosong, hentikan program dengan pesan jelas."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Environment variable '{name}' belum diisi di file .env! "
            f"Cek .env.example sebagai contoh."
        )
    return value


@dataclass(frozen=True)
class IndicatorConfig:
    """Pengaturan indikator teknikal sesuai setup TradingView kamu."""
    ma_fast: int = 5
    ma_slow: int = 20
    ma_type: str = "ema"        # "ema" atau "sma"
    rsi_length: int = 14
    rsi_ma_length: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0


@dataclass(frozen=True)
class ChannelsConfig:
    """ID channel Discord untuk auto-post tiap fitur (opsional)."""
    briefing: int | None = None
    news: int | None = None
    calendar: int | None = None
    alerts: int | None = None
    signals: int | None = None


@dataclass(frozen=True)
class Settings:
    """Objek konfigurasi tunggal yang dipakai di seluruh bagian bot."""
    discord_token: str
    database_url: str
    guild_id: int | None
    gemini_api_key: str | None
    twelvedata_api_key: str | None

    bot_name: str = "BotBawel"
    timezone_name: str = "Asia/Jakarta"
    language: str = "id"
    default_watchlist: list[dict[str, str]] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=lambda: ["15m", "30m", "1h"])
    default_timeframe: str = "30m"
    briefing_times: list[str] = field(default_factory=lambda: ["07:00", "19:00"])
    calendar_min_impact: str = "medium"
    calendar_reminders: list[int] = field(default_factory=lambda: [30, 5])
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        """Objek timezone Python (default: Asia/Jakarta / WIB)."""
        return ZoneInfo(self.timezone_name)


def _to_int_or_none(val: Any) -> int | None:
    if val is None or str(val).strip() == "":
        return None
    return int(val)


def load_settings() -> Settings:
    """Baca .env dan config.yaml lalu gabungkan menjadi objek Settings."""
    config_path = ROOT_DIR / "config.yaml"
    cfg: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    ind_raw = cfg.get("indicators", {}) or {}
    indicators = IndicatorConfig(
        ma_fast=int(ind_raw.get("ma_fast", 5)),
        ma_slow=int(ind_raw.get("ma_slow", 20)),
        ma_type=str(ind_raw.get("ma_type", "ema")).lower(),
        rsi_length=int(ind_raw.get("rsi_length", 14)),
        rsi_ma_length=int(ind_raw.get("rsi_ma_length", 14)),
        rsi_overbought=float(ind_raw.get("rsi_overbought", 70)),
        rsi_oversold=float(ind_raw.get("rsi_oversold", 30)),
    )

    ch_raw = cfg.get("channels", {}) or {}
    channels = ChannelsConfig(
        briefing=_to_int_or_none(ch_raw.get("briefing")),
        news=_to_int_or_none(ch_raw.get("news")),
        calendar=_to_int_or_none(ch_raw.get("calendar")),
        alerts=_to_int_or_none(ch_raw.get("alerts")),
        signals=_to_int_or_none(ch_raw.get("signals")),
    )

    cal_raw = cfg.get("calendar", {}) or {}
    guild_id_str = os.getenv("DISCORD_GUILD_ID", "").strip()

    return Settings(
        discord_token=_require_env("DISCORD_TOKEN"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/botbawel",
        ).strip(),
        guild_id=int(guild_id_str) if guild_id_str else None,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        twelvedata_api_key=os.getenv("TWELVEDATA_API_KEY", "").strip() or None,
        bot_name=cfg.get("bot_name", "BotBawel"),
        timezone_name=cfg.get("timezone", "Asia/Jakarta"),
        language=cfg.get("language", "id"),
        default_watchlist=cfg.get("watchlist", []),
        timeframes=cfg.get("timeframes", ["15m", "30m", "1h"]),
        default_timeframe=cfg.get("default_timeframe", "30m"),
        briefing_times=cfg.get("briefing_times", ["07:00", "19:00"]),
        calendar_min_impact=str(cal_raw.get("min_impact", "medium")).lower(),
        calendar_reminders=list(cal_raw.get("reminders_minutes", [30, 5])),
        indicators=indicators,
        channels=channels,
        raw=cfg,
    )
