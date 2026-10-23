"""
bot/discord_bot/cogs/alerts.py
------------------------------
Fitur F7 (Price Alert):
- `/alert add <symbol> <condition> <price>` -> Pasang alarm harga (above / below)
- `/alert list`                             -> Lihat daftar alarm harga yang aktif
- `/alert remove <id>`                      -> Hapus alarm berdasarkan ID
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select

from bot.collectors.prices.base import normalize_symbol
from bot.db.models import Alert
from bot.db.session import get_session

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


class AlertsCog(commands.Cog):
    """Cog untuk mengelola alarm/alert harga aset."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    alert_group = app_commands.Group(
        name="alert", description="Pasang dan kelola alarm harga aset (Price Alert)"
    )

    @alert_group.command(
        name="add",
        description="Pasang alarm saat harga menembus ke atas (above) atau ke bawah (below) level tertentu",
    )
    @app_commands.describe(
        symbol="Contoh: BTC, ETH, XAUUSD",
        condition="Pilih 'above' (di atas) atau 'below' (di bawah)",
        target_price="Level harga target (contoh: 95000)",
    )
    async def alert_add(
        self,
        interaction: discord.Interaction,
        symbol: str,
        condition: Literal["above", "below"],
        target_price: float,
    ) -> None:
        await interaction.response.defer()
        norm_sym, _ = normalize_symbol(symbol)

        try:
            ticker = await self.bot.price_router.get_ticker(norm_sym)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Gagal mengecek simbol `{norm_sym}`: {e}", ephemeral=True
            )
            return

        async with get_session() as session:
            new_alert = Alert(
                symbol=norm_sym,
                condition=condition,
                value=target_price,
                channel_id=interaction.channel_id,
                active=True,
            )
            session.add(new_alert)
            await session.commit()
            await session.refresh(new_alert)

        arah = "menembus ke atas (>=)" if condition == "above" else "turun ke bawah (<=)"
        await interaction.followup.send(
            f"🔔 **Alert #{new_alert.id} dipasang!**\n"
            f"Aset: **{norm_sym}** (Harga sekarang: `${ticker.price:,.2f}`)\n"
            f"Syarat: Harga {arah} **${target_price:,.2f}**"
        )

    @alert_group.command(name="list", description="Lihat semua alarm harga yang sedang aktif")
    async def alert_list(self, interaction: discord.Interaction) -> None:
        async with get_session() as session:
            alerts = list(
                (
                    await session.execute(
                        select(Alert).where(Alert.active.is_(True)).order_by(Alert.id.asc())
                    )
                )
                .scalars()
                .all()
            )

        if not alerts:
            await interaction.response.send_message("🔕 Belum ada price alert yang aktif.")
            return

        lines = [
            f"• **ID #{a.id}** — `{a.symbol}` **{a.condition.upper()}** `${a.value:,.2f}`"
            for a in alerts
        ]
        embed = discord.Embed(
            title="🔔 Daftar Price Alert Aktif",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    @alert_group.command(name="remove", description="Hapus alarm harga berdasarkan nomor ID")
    @app_commands.describe(alert_id="Nomor ID alert (cek di /alert list)")
    async def alert_remove(self, interaction: discord.Interaction, alert_id: int) -> None:
        async with get_session() as session:
            res = await session.execute(delete(Alert).where(Alert.id == alert_id))
            await session.commit()

        if res.rowcount:
            await interaction.response.send_message(f"🗑️ Alert **#{alert_id}** berhasil dihapus.")
        else:
            await interaction.response.send_message(
                f"⚠️ Alert **#{alert_id}** tidak ditemukan.", ephemeral=True
            )


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(AlertsCog(bot))
