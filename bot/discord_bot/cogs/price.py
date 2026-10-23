"""
bot/discord_bot/cogs/price.py
-----------------------------
Fitur F1 (Price Check) & F2 (Watchlist):
- `/price <symbol>`            -> Cek harga terkini, % 24 jam, high/low 24 jam
- `/watchlist list`            -> Lihat semua aset di watchlist + harga saat ini
- `/watchlist add <symbol>`    -> Tambah aset baru ke watchlist PostgreSQL
- `/watchlist remove <symbol>` -> Hapus aset dari watchlist PostgreSQL
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select

from bot.collectors.prices.base import normalize_symbol
from bot.db.models import Watchlist
from bot.db.session import get_session

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


class PriceCog(commands.Cog):
    """Cog untuk pengecekan harga & pengelolaan Watchlist."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    @app_commands.command(
        name="price",
        description="Cek harga aset terkini, perubahan 24 jam, serta High/Low (contoh: BTC, ETH, XAUUSD)",
    )
    @app_commands.describe(symbol="Simbol aset, misal: BTC, ETH, SOL, XAUUSD")
    async def price(self, interaction: discord.Interaction, symbol: str) -> None:
        await interaction.response.defer()
        try:
            ticker = await self.bot.price_router.get_ticker(symbol)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Gagal mengambil harga untuk `{symbol}`: {e}", ephemeral=True
            )
            return

        is_up = ticker.change_24h_pct >= 0
        arrow = "🟢 ▲" if is_up else "🔴 ▼"
        color = discord.Color.green() if is_up else discord.Color.red()

        embed = discord.Embed(
            title=f"💰 {ticker.symbol} ({ticker.market.upper()})",
            color=color,
            timestamp=ticker.timestamp,
        )
        embed.add_field(name="Harga Saat Ini", value=f"**${ticker.price:,.2f}**", inline=True)
        embed.add_field(
            name="Perubahan 24 Jam",
            value=f"{arrow} **{ticker.change_24h_pct:+.2f}%**",
            inline=True,
        )
        embed.add_field(
            name="Range 24 Jam",
            value=f"High: `${ticker.high_24h:,.2f}`\nLow: `${ticker.low_24h:,.2f}`",
            inline=False,
        )
        embed.set_footer(text=f"Sumber: {ticker.source} • BotBawel")
        await interaction.followup.send(embed=embed)

    watchlist_group = app_commands.Group(
        name="watchlist", description="Kelola daftar aset yang dipantau BotBawel"
    )

    @watchlist_group.command(name="list", description="Tampilkan daftar watchlist beserta harganya")
    async def watchlist_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        async with get_session() as session:
            items = list(
                (await session.execute(select(Watchlist).order_by(Watchlist.id.asc()))).scalars().all()
            )

        if not items:
            await interaction.followup.send("📋 Watchlist masih kosong. Gunakan `/watchlist add`.")
            return

        lines: list[str] = []
        for item in items:
            try:
                t = await self.bot.price_router.get_ticker(item.symbol)
                icon = "🟢" if t.change_24h_pct >= 0 else "🔴"
                lines.append(
                    f"{icon} **{item.symbol}** (`{item.market}`) — **${t.price:,.2f}** ({t.change_24h_pct:+.2f}%)"
                )
            except Exception:
                lines.append(f"⚪ **{item.symbol}** (`{item.market}`) — _harga belum tersedia_")

        embed = discord.Embed(
            title="📋 Watchlist BotBawel",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed)

    @watchlist_group.command(name="add", description="Tambahkan simbol aset ke dalam watchlist")
    @app_commands.describe(symbol="Contoh: BTC, ETH, SOL, XAUUSD")
    async def watchlist_add(self, interaction: discord.Interaction, symbol: str) -> None:
        await interaction.response.defer()
        norm_sym, market = normalize_symbol(symbol)

        try:
            ticker = await self.bot.price_router.get_ticker(norm_sym)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Simbol `{norm_sym}` tidak ditemukan di provider harga: {e}", ephemeral=True
            )
            return

        async with get_session() as session:
            exists = (
                await session.execute(select(Watchlist).where(Watchlist.symbol == norm_sym))
            ).scalar_one_or_none()
            if exists:
                await interaction.followup.send(f"ℹ️ `{norm_sym}` sudah ada di watchlist!")
                return
            session.add(Watchlist(symbol=norm_sym, market=market))
            await session.commit()

        await interaction.followup.send(
            f"✅ **{norm_sym}** (`{market}`) berhasil ditambahkan ke watchlist! Harga saat ini: **${ticker.price:,.2f}**"
        )

    @watchlist_group.command(name="remove", description="Hapus simbol aset dari watchlist")
    @app_commands.describe(symbol="Contoh: SOL, BTC/USDT, XAUUSD")
    async def watchlist_remove(self, interaction: discord.Interaction, symbol: str) -> None:
        norm_sym, _ = normalize_symbol(symbol)
        async with get_session() as session:
            res = await session.execute(delete(Watchlist).where(Watchlist.symbol == norm_sym))
            await session.commit()

        if res.rowcount:
            await interaction.response.send_message(f"🗑️ **{norm_sym}** dihapus dari watchlist.")
        else:
            await interaction.response.send_message(
                f"⚠️ `{norm_sym}` tidak ditemukan di watchlist.", ephemeral=True
            )


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(PriceCog(bot))
