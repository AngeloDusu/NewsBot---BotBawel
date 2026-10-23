"""
bot/scheduler.py
----------------
Mengatur seluruh pekerjaan terjadwal (background jobs) menggunakan `AsyncIOScheduler` (APScheduler)
di dalam proses BotBawel:
1. Cek Price Alerts               -> tiap 1 menit
2. Cek Reminder Kalender Ekonomi  -> tiap 1 menit (notif H-30 menit & H-5 menit sebelum rilis)
3. Ambil Berita Baru + Ringkas AI -> tiap 10 menit
4. Signal Scanner Watchlist       -> tiap 15 menit (menit 0, 15, 30, 45 saat candle 15m/30m close)
5. Sinkronisasi Kalender Ekonomi  -> tiap 2 jam
6. Daily Briefing Pagi & Malam    -> jam 07:00 WIB & 19:00 WIB
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import select

from bot.collectors.calendar import sync_economic_calendar
from bot.collectors.news import collect_and_store_new_news
from bot.db.models import EconEvent
from bot.db.session import get_session
from bot.discord_bot.cogs.briefing import build_briefing_embed
from bot.discord_bot.cogs.news import build_news_embed
from bot.services.alert_engine import check_active_alerts

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


async def _job_check_alerts(bot: BotBawel) -> None:
    """Cek apakah ada target harga (/alert) yang tersentuh."""
    triggered = await check_active_alerts(bot.price_router)
    if not triggered:
        return

    for t in triggered:
        ch = await bot.get_target_channel(t.channel_id or bot.settings.channels.alerts)
        if ch:
            arah = "menembus ke atas (>=)" if t.condition == "above" else "turun ke bawah (<=)"
            embed = discord.Embed(
                title=f"🚨 PRICE ALERT TERPICU: {t.symbol}",
                description=(
                    f"Harga **{t.symbol}** telah {arah} target **${t.target_value:,.2f}**!\n"
                    f"Harga saat ini: **${t.current_price:,.2f}**"
                ),
                color=discord.Color.red() if t.condition == "below" else discord.Color.green(),
            )
            embed.set_footer(text=f"Alert ID #{t.alert_id} otomatis dinonaktifkan • BotBawel")
            await ch.send(embed=embed)


async def _job_check_calendar_reminders(bot: BotBawel) -> None:
    """Kirim pengingat 30 menit dan 5 menit sebelum event ekonomi High Impact rilis."""
    now = datetime.now(timezone.utc)
    win_35m = now + timedelta(minutes=35)

    async with get_session() as session:
        events = list(
            (
                await session.execute(
                    select(EconEvent).where(
                        EconEvent.event_time > now,
                        EconEvent.event_time <= win_35m,
                        EconEvent.impact == "High",
                    )
                )
            )
            .scalars()
            .all()
        )
        if not events:
            return

        ch = await bot.get_target_channel(bot.settings.channels.calendar)
        tz = bot.settings.tz

        for ev in events:
            mins_left = (ev.event_time - now).total_seconds() / 60.0
            local_time = ev.event_time.astimezone(tz).strftime("%H:%M WIB")

            if 5 < mins_left <= 30 and not ev.reminded_30m:
                ev.reminded_30m = True
                if ch:
                    await ch.send(
                        f"⏰ **Reminder Kalender Ekonomi (~{int(mins_left)} menit lagi • {local_time})**\n"
                        f"🔴 **[{ev.country}] {ev.title}**\n"
                        f"Forecast: `{ev.forecast or '-'}` | Previous: `{ev.previous or '-'}`"
                    )
            elif 0 < mins_left <= 5 and not ev.reminded_5m:
                ev.reminded_5m = True
                if ch:
                    await ch.send(
                        f"🚨 **5 MENIT LAGI RILIS DATA HIGH IMPACT ({local_time})!**\n"
                        f"🔴 **[{ev.country}] {ev.title}** — Hati-hati volatilitas tinggi di XAU/USD & Crypto!"
                    )

        await session.commit()


async def _job_collect_news(bot: BotBawel) -> None:
    """Ambil berita baru dari RSS, ringkas dengan AI, dan post ke #news jika dikonfigurasi."""
    new_items = await collect_and_store_new_news(bot.ai_service, limit_new=2)
    if not new_items or not bot.settings.channels.news:
        return

    ch = await bot.get_target_channel(bot.settings.channels.news)
    if not ch:
        return

    async with get_session() as session:
        for item in new_items:
            await ch.send(embed=build_news_embed(item))
            db_item = await session.get(type(item), item.id)
            if db_item:
                db_item.posted = True
        await session.commit()


async def _job_scan_signals(bot: BotBawel) -> None:
    """Scan watchlist setiap penutupan candle 15m; kirim jika ada cross EMA 5/20 baru di 30m."""
    embeds = await bot.scan_watchlist_signals(only_fresh_cross=True)
    if not embeds:
        return

    ch = await bot.get_target_channel(bot.settings.channels.signals)
    if ch:
        await ch.send(
            content="📡 **Signal Scanner: Terdeteksi EMA 5/20 Cross Baru di 30m!**",
            embeds=embeds[:5],
        )


async def _job_send_briefing(bot: BotBawel, label: str) -> None:
    """Kirim Daily Briefing otomatis (Pagi 07:00 WIB atau Malam 19:00 WIB)."""
    ch = await bot.get_target_channel(bot.settings.channels.briefing)
    if not ch:
        return
    embed = await build_briefing_embed(bot, kind=label)
    await ch.send(embed=embed)


def create_scheduler(bot: BotBawel) -> AsyncIOScheduler:
    """Buat dan daftarkan seluruh jadwal kerja otomatis ke AsyncIOScheduler."""
    tz = bot.settings.tz
    scheduler = AsyncIOScheduler(timezone=tz)

    # 1. Cek Price Alert tiap 1 menit
    scheduler.add_job(
        _job_check_alerts,
        IntervalTrigger(minutes=1, timezone=tz),
        args=[bot],
        id="check_alerts",
        replace_existing=True,
    )

    # 2. Cek Reminder Kalender Ekonomi tiap 1 menit
    scheduler.add_job(
        _job_check_calendar_reminders,
        IntervalTrigger(minutes=1, timezone=tz),
        args=[bot],
        id="calendar_reminders",
        replace_existing=True,
    )

    # 3. Ambil berita + AI summary tiap 10 menit
    scheduler.add_job(
        _job_collect_news,
        IntervalTrigger(minutes=10, timezone=tz),
        args=[bot],
        id="collect_news",
        replace_existing=True,
    )

    # 4. Signal Scanner tiap candle 15m close (menit 0, 15, 30, 45 lewat 5 detik)
    scheduler.add_job(
        _job_scan_signals,
        CronTrigger(minute="0,15,30,45", second="5", timezone=tz),
        args=[bot],
        id="signal_scanner",
        replace_existing=True,
    )

    # 5. Update Kalender Ekonomi tiap 2 jam
    scheduler.add_job(
        sync_economic_calendar,
        IntervalTrigger(hours=2, timezone=tz),
        kwargs={"min_impact": bot.settings.calendar_min_impact},
        id="sync_calendar",
        replace_existing=True,
    )

    # 6. Briefing Pagi (07:00 WIB) & Malam (19:00 WIB) sesuai config.yaml
    for time_str in bot.settings.briefing_times:
        try:
            hour_s, min_s = time_str.strip().split(":")
            hour_i, min_i = int(hour_s), int(min_s)
            label = "Pagi (07:00 WIB)" if hour_i < 12 else f"Malam ({time_str} WIB)"
            scheduler.add_job(
                _job_send_briefing,
                CronTrigger(hour=hour_i, minute=min_i, timezone=tz),
                args=[bot, label],
                id=f"briefing_{hour_i:02d}_{min_i:02d}",
                replace_existing=True,
            )
        except Exception as e:
            logger.warning(f"Format jam briefing '{time_str}' tidak valid: {e}")

    return scheduler
