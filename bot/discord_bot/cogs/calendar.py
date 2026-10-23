"""
bot/discord_bot/cogs/calendar.py
--------------------------------
Fitur F5 (Economic Calendar):
- `/calendar [periode]` -> Menampilkan jadwal rilis data ekonomi penting (CPI, NFP, FOMC, dll)
  dalam zona waktu WIB (`Asia/Jakarta`), lengkap dengan Forecast & Previous.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.collectors.calendar import get_upcoming_events, sync_economic_calendar

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


class CalendarCog(commands.Cog):
    """Cog untuk jadwal kalender ekonomi (ForexFactory feed)."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    @app_commands.command(
        name="calendar",
        description="Lihat jadwal rilis data ekonomi penting (CPI, NFP, FOMC, dll) dalam waktu WIB",
    )
    @app_commands.describe(periode="Pilih jadwal hari ini (24 jam) atau minggu ini (7 hari)")
    async def calendar(
        self,
        interaction: discord.Interaction,
        periode: Literal["today", "week"] = "today",
    ) -> None:
        await interaction.response.defer()

        await sync_economic_calendar(min_impact=self.bot.settings.calendar_min_impact)

        hours = 24 if periode == "today" else 168
        events = await get_upcoming_events(
            hours_ahead=hours, min_impact=self.bot.settings.calendar_min_impact
        )

        if not events:
            await interaction.followup.send(
                f"📅 Tidak ada jadwal ekonomi berdampak High/Medium dalam periode **{periode}**."
            )
            return

        tz = self.bot.settings.tz
        lines: list[str] = []
        for ev in events[:15]:
            local_dt = ev.event_time.astimezone(tz)
            time_str = local_dt.strftime("%d %b • %H:%M WIB")
            icon = "🔴" if ev.impact.lower() == "high" else "🟠"
            actual_str = f" | Actual: **{ev.actual}**" if ev.actual else ""
            lines.append(
                f"{icon} **{time_str}** — `[{ev.country}]` **{ev.title}**\n"
                f"   ↳ Forecast: `{ev.forecast or '-'}` | Prev: `{ev.previous or '-'}`{actual_str}"
            )

        embed = discord.Embed(
            title=f"📅 Kalender Ekonomi ({'24 Jam Ke Depan' if periode == 'today' else 'Minggu Ini'})",
            description="\n\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text="🔴 High Impact • 🟠 Medium Impact • Sumber: ForexFactory • Zona waktu: WIB"
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(CalendarCog(bot))
