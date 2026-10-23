"""
bot/collectors/calendar.py
--------------------------
Mengambil jadwal kalender ekonomi mingguan (CPI, NFP, FOMC, Jobless Claims, PMI, dll)
dari JSON feed gratis ForexFactory (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`)
dan menyimpannya ke tabel `econ_events` di PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.db.models import EconEvent
from bot.db.session import get_session

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

IMPACT_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


async def sync_economic_calendar(min_impact: str = "medium") -> int:
    """
    Unduh jadwal kalender ekonomi minggu ini dari ForexFactory feed
    dan simpan/update ke tabel `econ_events` PostgreSQL.
    Mengembalikan jumlah event yang disimpan.
    """
    min_rank = IMPACT_RANK.get(min_impact.lower(), 2)
    headers = {"User-Agent": "BotBawel/1.0"}

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            resp = await client.get(FF_CALENDAR_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"Gagal mengambil feed kalender ekonomi: {e}")
        return 0

    rows_to_upsert: list[dict] = []
    for item in data:
        impact = str(item.get("impact", "Low")).strip()
        if IMPACT_RANK.get(impact.lower(), 0) < min_rank:
            continue

        date_str = item.get("date")
        if not date_str:
            continue
        try:
            event_dt = datetime.fromisoformat(date_str).astimezone(timezone.utc)
        except Exception:
            continue

        rows_to_upsert.append(
            {
                "country": str(item.get("country", "USD")).upper()[:16],
                "title": str(item.get("title", "Economic Event"))[:256],
                "impact": impact[:16],
                "event_time": event_dt,
                "forecast": str(item.get("forecast") or "-")[:64],
                "previous": str(item.get("previous") or "-")[:64],
                "actual": str(item.get("actual") or "")[:64] or None,
            }
        )

    if not rows_to_upsert:
        return 0

    async with get_session() as session:
        stmt = pg_insert(EconEvent).values(rows_to_upsert)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_event_country_title_time",
            set_={
                "impact": stmt.excluded.impact,
                "forecast": stmt.excluded.forecast,
                "previous": stmt.excluded.previous,
                "actual": stmt.excluded.actual,
            },
        )
        await session.execute(stmt)
        await session.commit()

    return len(rows_to_upsert)


async def get_upcoming_events(
    hours_ahead: int = 24, min_impact: str = "medium"
) -> list[EconEvent]:
    """Ambil daftar event ekonomi yang akan datang dari database."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta

    end_time = now + timedelta(hours=hours_ahead)
    allowed_impacts = ["High", "Medium"] if min_impact.lower() == "medium" else ["High"]

    async with get_session() as session:
        stmt = (
            select(EconEvent)
            .where(
                EconEvent.event_time >= now - timedelta(hours=2),
                EconEvent.event_time <= end_time,
                EconEvent.impact.in_(allowed_impacts),
            )
            .order_by(EconEvent.event_time.asc())
        )
        return list((await session.execute(stmt)).scalars().all())
