"""
bot/discord_bot/cogs/briefing.py
--------------------------------
Fitur F10 (Briefing):
- Otomatis jalan jam 07:00 WIB & 19:00 WIB lewat APScheduler
- Bisa dipanggil manual kapan saja dengan perintah `/briefing`
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.collectors.calendar import get_upcoming_events, sync_economic_calendar
from bot.collectors.news import collect_and_store_new_news
from bot.db.models import Briefing, News, Watchlist
from bot.db.session import get_session

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


async def build_briefing_embed(bot: BotBawel, kind: str = "Manual") -> discord.Embed:
    """
    Kumpulkan:
    1. Harga terkini seluruh aset di Watchlist
    2. 3 Berita terbaru beserta sentimen AI
    3. Jadwal kalender ekonomi High/Medium 24 jam ke depan
    Lalu minta AI menyusun rangkuman Bahasa Indonesia & simpan ke tabel `briefings`.
    """
    async with get_session() as session:
        watchlist_items = list(
            (await session.execute(select(Watchlist).order_by(Watchlist.id.asc()))).scalars().all()
        )

    ticker_lines: list[str] = []
    for item in watchlist_items:
        try:
            t = await bot.price_router.get_ticker(item.symbol)
            icon = "🟢" if t.change_24h_pct >= 0 else "🔴"
            ticker_lines.append(
                f"- {icon} {t.symbol}: ${t.price:,.2f} ({t.change_24h_pct:+.2f}% | H: ${t.high_24h:,.2f} L: ${t.low_24h:,.2f})"
            )
        except Exception:
            ticker_lines.append(f"- {item.symbol}: data harga belum tersedia")

    await collect_and_store_new_news(bot.ai_service, limit_new=2)
    async with get_session() as session:
        recent_news = list(
            (
                await session.execute(
                    select(News).order_by(News.published_at.desc(), News.id.desc()).limit(3)
                )
            )
            .scalars()
            .all()
        )
    news_lines = [
        f"- [{n.sentiment or 'Netral'}] {n.title} ({n.source}): {n.summary_id or ''}"
        for n in recent_news
    ]

    await sync_economic_calendar(min_impact=bot.settings.calendar_min_impact)
    upcoming = await get_upcoming_events(
        hours_ahead=24, min_impact=bot.settings.calendar_min_impact
    )
    tz = bot.settings.tz
    event_lines = [
        f"- [{ev.impact}] {ev.event_time.astimezone(tz).strftime('%H:%M WIB')} {ev.country} {ev.title} "
        f"(Forecast: {ev.forecast or '-'}, Prev: {ev.previous or '-'})"
        for ev in upcoming[:6]
    ]

    content = await bot.ai_service.generate_briefing(
        kind=kind,
        tickers_summary=ticker_lines,
        news_summary=news_lines,
        events_summary=event_lines,
    )

    async with get_session() as session:
        session.add(Briefing(kind=kind.lower(), content=content))
        await session.commit()

    now_wib = datetime.now(tz)
    embed = discord.Embed(
        title=f"🗞️ BotBawel Briefing — {kind} ({now_wib.strftime('%d %b %Y • %H:%M WIB')})",
        description=content[:4000],
        color=discord.Color.teal(),
        timestamp=now_wib,
    )
    embed.set_footer(text="Jadwal otomatis: 07:00 & 19:00 WIB • Ketik /briefing kapan saja")
    return embed


class BriefingCog(commands.Cog):
    """Cog untuk perintah /briefing on-demand."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    @app_commands.command(
        name="briefing",
        description="Minta rangkuman pasar lengkap (harga watchlist, berita AI, & kalender ekonomi) saat ini juga",
    )
    async def briefing(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        embed = await build_briefing_embed(self.bot, kind="On-Demand (Manual)")
        await interaction.followup.send(embed=embed)


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(BriefingCog(bot))
