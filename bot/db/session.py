"""
bot/db/session.py
-----------------
Mengelola koneksi asynchronous ke PostgreSQL menggunakan SQLAlchemy + asyncpg.
Menyediakan:
- `init_db()`      -> buat engine, buat semua tabel jika belum ada, isi watchlist awal
- `get_session()`  -> context manager untuk transaksi database yang aman
- `dispose_db()`   -> tutup koneksi saat bot dimatikan
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base, Watchlist

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Inisialisasi SQLAlchemy async engine & session factory."""
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        pool_pre_ping=True,  # cek koneksi hidup sebelum dipakai
        echo=False,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context manager untuk membuka dan menutup session database secara rapi."""
    if _session_factory is None:
        raise RuntimeError("Database belum diinisialisasi. Panggil init_db() terlebih dahulu.")
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db(database_url: str, default_watchlist: list[dict[str, str]] | None = None) -> str:
    """
    1. Buka engine PostgreSQL
    2. Tes koneksi & ambil versi PostgreSQL
    3. Buat semua tabel otomatis (CREATE TABLE IF NOT EXISTS)
    4. Isi watchlist awal dari config.yaml jika tabel watchlist masih kosong
    """
    engine = init_engine(database_url)

    async with engine.begin() as conn:
        version_res = await conn.execute(text("SELECT version()"))
        pg_version = str(version_res.scalar_one())
        await conn.run_sync(Base.metadata.create_all)

    if default_watchlist:
        async with get_session() as session:
            existing = (await session.execute(select(Watchlist))).scalars().all()
            if not existing:
                for item in default_watchlist:
                    sym = item.get("symbol", "").upper().strip()
                    mkt = item.get("market", "crypto").lower().strip()
                    if sym:
                        session.add(Watchlist(symbol=sym, market=mkt))
                await session.commit()
                logger.info(f"Watchlist awal berhasil diisi: {[i['symbol'] for i in default_watchlist]}")

    return pg_version


async def dispose_db() -> None:
    """Tutup semua koneksi pool saat bot berhenti."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
