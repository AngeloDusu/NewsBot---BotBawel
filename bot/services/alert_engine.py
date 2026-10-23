"""
bot/services/alert_engine.py
----------------------------
Mengecek seluruh price alert aktif (`active == True`) di PostgreSQL terhadap harga
pasar terkini. Jika harga menembus target (`above` atau `below`), tandai alert
sebagai selesai (`active = False`, isi `triggered_at`) dan kembalikan daftar alert
yang terpicu untuk dikirim ke Discord.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from bot.collectors.prices.router import MarketPriceRouter
from bot.db.models import Alert
from bot.db.session import get_session


@dataclass
class TriggeredAlert:
    alert_id: int
    symbol: str
    condition: str
    target_value: float
    current_price: float
    channel_id: int | None


async def check_active_alerts(price_router: MarketPriceRouter) -> list[TriggeredAlert]:
    """Periksa semua alert aktif dan kembalikan yang syaratnya terpenuhi."""
    async with get_session() as session:
        active_alerts = list(
            (await session.execute(select(Alert).where(Alert.active.is_(True)))).scalars().all()
        )
        if not active_alerts:
            return []

        # Ambil harga per simbol unik supaya hemat request API
        symbols = {a.symbol for a in active_alerts}
        latest_prices: dict[str, float] = {}
        for sym in symbols:
            try:
                ticker = await price_router.get_ticker(sym)
                latest_prices[sym] = ticker.price
            except Exception as e:
                logger.warning(f"Gagal cek harga untuk alert {sym}: {e}")

        triggered: list[TriggeredAlert] = []
        now = datetime.now(timezone.utc)

        for alert in active_alerts:
            price = latest_prices.get(alert.symbol)
            if price is None:
                continue

            hit = (alert.condition == "above" and price >= alert.value) or (
                alert.condition == "below" and price <= alert.value
            )
            if hit:
                alert.active = False
                alert.triggered_at = now
                triggered.append(
                    TriggeredAlert(
                        alert_id=alert.id,
                        symbol=alert.symbol,
                        condition=alert.condition,
                        target_value=alert.value,
                        current_price=price,
                        channel_id=alert.channel_id,
                    )
                )

        if triggered:
            await session.commit()

        return triggered
