"""
bot/discord_bot/client.py
-------------------------
Class utama `BotBawel` (turunan `commands.Bot`) yang menyatukan:
- Koneksi Discord & registrasi seluruh Cog (`price`, `news`, `calendar`, `alerts`, `analysis`, `briefing`)
- Koneksi ke `MarketPriceRouter`, `AIService`, dan `APScheduler`
- Helper pengiriman pesan otomatis ke channel Discord (`#briefing`, `#news`, `#calendar`, `#alerts`, `#signals`)
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger
from sqlalchemy import select

from bot.collectors.prices.router import MarketPriceRouter
from bot.config import Settings
from bot.db.models import Signal, Watchlist
from bot.db.session import dispose_db, get_session
from bot.discord_bot.cogs.analysis import build_confluence_embed
from bot.scheduler import create_scheduler
from bot.services.ai import AIService
from bot.services.technical import analyze_candles, evaluate_confluence

COGS = [
    "bot.discord_bot.cogs.price",
    "bot.discord_bot.cogs.news",
    "bot.discord_bot.cogs.calendar",
    "bot.discord_bot.cogs.alerts",
    "bot.discord_bot.cogs.analysis",
    "bot.discord_bot.cogs.briefing",
]


class BotBawel(commands.Bot):
    """Inti Bot Discord BotBawel."""

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.price_router = MarketPriceRouter(twelvedata_api_key=settings.twelvedata_api_key)
        self.ai_service = AIService(api_key=settings.gemini_api_key)
        self.scheduler = create_scheduler(self)

        # Daftarkan perintah dasar /ping
        @self.tree.command(
            name="ping",
            description="Cek status BotBawel, latensi Discord, dan status modul",
        )
        async def ping_cmd(interaction: discord.Interaction) -> None:
            latency_ms = round(self.latency * 1000)
            ai_status = "Aktif (Gemini)" if self.ai_service.is_enabled else "Mode Fallback (Tanpa API Key)"
            await interaction.response.send_message(
                f"🏓 **Pong! {self.settings.bot_name} aktif!**\n"
                f"• Latensi Gateway: `{latency_ms} ms`\n"
                f"• AI Service: `{ai_status}`\n"
                f"• Zona Waktu: `{self.settings.timezone_name}`"
            )

    async def setup_hook(self) -> None:
        """Dipanggil otomatis oleh discord.py sebelum bot siap menerima event."""
        for ext in COGS:
            await self.load_extension(ext)
            logger.info(f"Cog berhasil dimuat: {ext}")

        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(
                f"{len(synced)} slash commands berhasil di-sync ke server ID {self.settings.guild_id}"
            )
        else:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} slash commands di-sync secara global")

    async def on_ready(self) -> None:
        logger.info(f"✅ {self.user} sudah online dan siap!")
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("⏰ APScheduler telah aktif dan berjalan di background.")

    async def close(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        await self.price_router.close()
        await dispose_db()
        await super().close()

    async def get_target_channel(
        self, configured_id: int | None
    ) -> discord.abc.Messageable | None:
        """Cari channel berdasarkan ID di config.yaml; bila kosong, gunakan channel teks pertama yang bisa diakses."""
        if configured_id:
            ch = self.get_channel(configured_id)
            if ch is None:
                try:
                    ch = await self.fetch_channel(configured_id)
                except Exception:
                    ch = None
            if isinstance(ch, discord.abc.Messageable):
                return ch

        # Fallback: cari channel teks pertama di server tempat bot punya izin kirim pesan
        for guild in self.guilds:
            me = guild.me
            for channel in guild.text_channels:
                if me and channel.permissions_for(me).send_messages:
                    return channel
        return None

    async def scan_watchlist_signals(
        self, only_fresh_cross: bool = True
    ) -> list[discord.Embed]:
        """Pindai seluruh aset di watchlist untuk mencari setup teknikal 15m/30m/1h."""
        async with get_session() as session:
            items = list(
                (await session.execute(select(Watchlist).order_by(Watchlist.id.asc()))).scalars().all()
            )

        embeds: list[discord.Embed] = []
        cfg = self.settings.indicators

        for item in items:
            try:
                norm_sym, _, c15 = await self.price_router.get_candles(item.symbol, "15m", limit=80)
                _, _, c30 = await self.price_router.get_candles(norm_sym, "30m", limit=80)
                _, _, c1h = await self.price_router.get_candles(norm_sym, "1h", limit=80)

                tf_15m = analyze_candles(norm_sym, "15m", c15, cfg)
                tf_30m = analyze_candles(norm_sym, "30m", c30, cfg)
                tf_1h = analyze_candles(norm_sym, "1h", c1h, cfg)

                sig = evaluate_confluence(
                    tf_15m, tf_30m, tf_1h, require_fresh_cross=only_fresh_cross
                )
                if only_fresh_cross and sig.stars == 0:
                    continue

                if only_fresh_cross:
                    async with get_session() as session:
                        session.add(
                            Signal(
                                symbol=norm_sym,
                                timeframe="30m",
                                signal_type=tf_30m.cross_event or "TREND",
                                direction=sig.direction,
                                stars=sig.stars,
                                price=tf_30m.last_price,
                                details=sig.trigger_reason,
                            )
                        )
                        await session.commit()

                embeds.append(build_confluence_embed(sig, primary_tf="30m"))
            except Exception as e:
                logger.warning(f"Gagal scan sinyal {item.symbol}: {e}")

        return embeds
