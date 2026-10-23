"""
bot/main.py
-----------
Entry point utama untuk menyalakan BotBawel:
1. Muat konfigurasi dari `.env` dan `config.yaml`
2. Inisialisasi koneksi PostgreSQL, buat seluruh tabel otomatis, dan isi watchlist awal
3. Jalankan Discord Bot beserta seluruh Slash Commands dan APScheduler
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Pastikan root project ada di sys.path agar bisa dijalankan langsung (`python bot/main.py`)
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

from bot.config import load_settings
from bot.db.session import init_db
from bot.discord_bot.client import BotBawel


async def async_main() -> None:
    settings = load_settings()
    logger.info(f"🚀 Menyalakan {settings.bot_name} (Zona waktu: {settings.timezone_name})...")

    # Inisialisasi PostgreSQL & buat tabel otomatis
    pg_version = await init_db(
        database_url=settings.database_url,
        default_watchlist=settings.default_watchlist,
    )
    logger.info(f"🗄️ Terhubung ke PostgreSQL: {pg_version.splitlines()[0]}")

    bot = BotBawel(settings=settings)
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("👋 BotBawel dimatikan oleh user.")
