"""
bot/db/models.py
----------------
Definisi seluruh tabel database PostgreSQL menggunakan SQLAlchemy 2.0 ORM.
Sesuai dengan ERD di docs/plan.md:
1. Watchlist   -> daftar aset yang dipantau (BTC/USDT, ETH/USDT, XAU/USD)
2. Candle      -> cache data OHLCV per timeframe (15m, 30m, 1h)
3. News        -> berita ekonomi/crypto + hasil ringkasan & sentimen AI
4. EconEvent   -> jadwal kalender ekonomi (CPI, NFP, FOMC, dll)
5. Alert       -> target harga yang dipasang user (/alert)
6. Signal      -> histori sinyal teknikal yang ditemukan scanner
7. Briefing    -> histori rangkuman pasar harian/malam
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Class induk untuk semua tabel ORM."""
    pass


class Watchlist(Base):
    """Tabel daftar aset yang dipantau oleh BotBawel."""
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False, default="crypto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Candle(Base):
    """Cache data candlestick (OHLCV) supaya hemat kuota API."""
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_sym_tf_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class News(Base):
    """Berita market & ekonomi beserta ringkasan dan sentimen dari AI."""
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    summary_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Bullish/Bearish/Netral
    assets: Mapped[str | None] = mapped_column(String(128), nullable=True)    # mis. "BTC, ETH, USD"
    posted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class EconEvent(Base):
    """Jadwal rilis data kalender ekonomi (CPI, NFP, FOMC, dll)."""
    __tablename__ = "econ_events"
    __table_args__ = (
        UniqueConstraint("country", "title", "event_time", name="uq_event_country_title_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    impact: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # High/Medium/Low
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    forecast: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reminded_30m: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_5m: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    """Target alert harga yang dipasang user lewat /alert."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(16), nullable=False)  # "above" atau "below"
    value: Mapped[float] = mapped_column(Float, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Signal(Base):
    """Catatan sinyal teknikal yang dikirim ke channel #signals."""
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # Bullish / Bearish
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class Briefing(Base):
    """Arsip hasil briefing pagi/malam/manual."""
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # morning / evening / manual
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
