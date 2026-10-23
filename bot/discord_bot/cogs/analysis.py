"""
bot/discord_bot/cogs/analysis.py
--------------------------------
Fitur F8 (Technical Analysis) & F9 (Signal Scanner):
- `/analyze <symbol> [timeframe]` -> Analisis teknikal mendalam (EMA 5/20, RSI 14 + MA RSI,
  Support/Resistance, Channel Slope) + cek Konfluensi Multi-Timeframe (15m, 30m, 1h).
- `/scan` -> Jalankan pemindaian sinyal seluruh watchlist secara langsung.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.technical import ConfluenceSignal, analyze_candles, evaluate_confluence

if TYPE_CHECKING:
    from bot.discord_bot.client import BotBawel


def build_confluence_embed(sig: ConfluenceSignal, primary_tf: str = "30m") -> discord.Embed:
    """Buat Discord Embed untuk hasil Analisis Teknikal & Konfluensi 15m/30m/1h."""
    t30 = sig.tf_30m
    is_bull = sig.direction == "Bullish"
    color = discord.Color.green() if is_bull else discord.Color.red()
    badge = "🟢 BULLISH" if is_bull else "🔴 BEARISH"
    stars_str = "⭐" * max(sig.stars, 1)

    embed = discord.Embed(
        title=f"📈 Analisis Teknikal: {sig.symbol} (Fokus {primary_tf})",
        description=f"**Bias Multi-Timeframe:** {badge} ({stars_str})\n**Alasan:** {sig.trigger_reason}",
        color=color,
    )
    embed.add_field(
        name=f"💰 Harga & Level ({t30.timeframe})",
        value=(
            f"Harga: **${t30.last_price:,.2f}**\n"
            f"Resistance (30 candle): `${t30.resistance:,.2f}`\n"
            f"Support (30 candle): `${t30.support:,.2f}`"
        ),
        inline=True,
    )
    embed.add_field(
        name=f"📊 EMA 5/20 & RSI 14 ({t30.timeframe})",
        value=(
            f"EMA 5: `${t30.ma_fast_val:,.2f}`\n"
            f"EMA 20: `${t30.ma_slow_val:,.2f}`\n"
            f"RSI 14: **{t30.rsi_val:.1f}** (MA RSI: `{t30.rsi_ma_val:.1f}`)"
        ),
        inline=True,
    )
    embed.add_field(
        name="📐 Arah Channel",
        value=t30.channel_slope,
        inline=False,
    )

    if sig.tf_15m and sig.tf_1h:
        embed.add_field(
            name="🧭 Peta Konfluensi (15m • 30m • 1h)",
            value=(
                f"• **15m (Timing):** {sig.tf_15m.trend_bias} (RSI `{sig.tf_15m.rsi_val:.1f}`)\n"
                f"• **30m (Setup Utama):** {sig.tf_30m.trend_bias} (RSI `{sig.tf_30m.rsi_val:.1f}`)\n"
                f"• **1h (Tren Besar):** {sig.tf_1h.trend_bias} (RSI `{sig.tf_1h.rsi_val:.1f}`)"
            ),
            inline=False,
        )

    if t30.rsi_warning:
        embed.add_field(name="⚠️ Peringatan RSI", value=t30.rsi_warning, inline=False)

    embed.set_footer(
        text="⚠️ Hanya bahan pertimbangan teknikal, bukan nasihat finansial • BotBawel"
    )
    return embed


class AnalysisCog(commands.Cog):
    """Cog untuk perintah /analyze dan /scan."""

    def __init__(self, bot: BotBawel) -> None:
        self.bot = bot

    @app_commands.command(
        name="analyze",
        description="Analisis teknikal EMA 5/20, RSI 14, Support/Resistance & Konfluensi 15m/30m/1h",
    )
    @app_commands.describe(
        symbol="Contoh: BTC, ETH, XAUUSD",
        timeframe="Timeframe fokus utama (default: 30m)",
    )
    async def analyze(
        self,
        interaction: discord.Interaction,
        symbol: str,
        timeframe: Literal["15m", "30m", "1h"] = "30m",
    ) -> None:
        await interaction.response.defer()
        cfg = self.bot.settings.indicators

        try:
            norm_sym, _, c15 = await self.bot.price_router.get_candles(symbol, "15m", limit=80)
            _, _, c30 = await self.bot.price_router.get_candles(norm_sym, "30m", limit=80)
            _, _, c1h = await self.bot.price_router.get_candles(norm_sym, "1h", limit=80)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Gagal mengambil data candle untuk `{symbol}`: {e}", ephemeral=True
            )
            return

        tf_15m = analyze_candles(norm_sym, "15m", c15, cfg)
        tf_30m = analyze_candles(norm_sym, "30m", c30, cfg)
        tf_1h = analyze_candles(norm_sym, "1h", c1h, cfg)

        focus_map = {"15m": tf_15m, "30m": tf_30m, "1h": tf_1h}
        sig = evaluate_confluence(tf_15m, focus_map[timeframe], tf_1h, require_fresh_cross=False)

        embed = build_confluence_embed(sig, primary_tf=timeframe)
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="scan",
        description="Pindai seluruh aset di watchlist sekarang untuk melihat setup 15m/30m/1h",
    )
    async def scan_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        embeds = await self.bot.scan_watchlist_signals(only_fresh_cross=False)
        if not embeds:
            await interaction.followup.send("ℹ️ Belum ada aset di watchlist untuk dipindai.")
            return
        await interaction.followup.send(
            content="🔍 **Hasil Pemindaian Multi-Timeframe Watchlist:**", embeds=embeds[:5]
        )


async def setup(bot: BotBawel) -> None:
    await bot.add_cog(AnalysisCog(bot))
