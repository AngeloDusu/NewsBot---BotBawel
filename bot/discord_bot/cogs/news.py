"""
bot/discord_bot/cogs/news.py
----------------------------
Fitur F3 (News Feed) & F4 (AI Summary & Sentiment):
- `/news [refresh]` -> Ambil & ringkas berita terbaru dengan AI dalam Bahasa Indonesia
- Menyediakan fungsi `build_news_embed()` yang juga dipakai oleh scheduler otomatis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.collectors.news import collect_and_store_new_news
from bot.db.models import News
from bot.db.session import get_session

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


def build_news_embed(news_item: News) -> discord.Embed:
    """Buat tampilan Discord Embed untuk satu berita + sentimen AI."""
    sentiment = (news_item.sentiment or "Netral").capitalize()
    if sentiment == "Bullish":
        badge = "🟢 Bullish"
        color = discord.Color.green()
    elif sentiment == "Bearish":
        badge = "🔴 Bearish"
        color = discord.Color.red()
    else:
        badge = "⚪ Netral"
        color = discord.Color.light_grey()

    embed = discord.Embed(
        title=news_item.title[:250],
        url=news_item.url,
        description=news_item.summary_id or news_item.title,
        color=color,
        timestamp=news_item.published_at,
    )
    embed.add_field(name="Sentimen AI", value=f"**{badge}**", inline=True)
    embed.add_field(name="Aset Terdampak", value=f"`{news_item.assets or 'Market'}`", inline=True)
    embed.set_footer(text=f"Sumber: {news_item.source} • Ringkasan oleh BotBawel AI")
    return embed


class NewsCog(commands.Cog):
    """Cog untuk menampilkan berita ekonomi & crypto beserta ringkasan AI."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    @app_commands.command(
        name="news",
        description="Tampilkan berita crypto & ekonomi terbaru beserta ringkasan dan sentimen AI",
    )
    @app_commands.describe(refresh="Ambil berita baru dari RSS terlebih dahulu?")
    async def news(
        self,
        interaction: discord.Interaction,
        refresh: Literal["ya", "tidak"] = "ya",
    ) -> None:
        await interaction.response.defer()

        if refresh == "ya":
            await collect_and_store_new_news(self.bot.ai_service, limit_new=3)

        async with get_session() as session:
            rows = list(
                (
                    await session.execute(
                        select(News).order_by(News.published_at.desc(), News.id.desc()).limit(3)
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            await interaction.followup.send("📭 Belum ada berita yang tersimpan saat ini.")
            return

        embeds = [build_news_embed(r) for r in rows]
        await interaction.followup.send(
            content="📰 **3 Berita & Analisis Sentimen Terbaru:**", embeds=embeds
        )


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(NewsCog(bot))
