"""
bot/collectors/news.py
----------------------
Mengambil berita terbaru dari RSS feed publik (CoinDesk, Cointelegraph, CNBC Economy),
melakukan deduplikasi berdasarkan URL di tabel `news` PostgreSQL, dan mengembalikan
daftar berita baru yang belum pernah diproses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from loguru import logger
from sqlalchemy import select

from bot.db.models import News
from bot.db.session import get_session

RSS_FEEDS: list[tuple[str, str, str]] = [
    ("CoinDesk", "crypto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "crypto", "https://cointelegraph.com/rss"),
    ("CNBC Economy", "macro", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
]


@dataclass
class RawNewsItem:
    source: str
    category: str
    title: str
    url: str
    summary_raw: str
    published_at: datetime


def _parse_pubdate(entry: dict) -> datetime:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


async def fetch_rss_items(category_filter: str | None = None, max_per_feed: int = 5) -> list[RawNewsItem]:
    """Ambil berita mentah dari daftar RSS feed."""
    items: list[RawNewsItem] = []
    headers = {"User-Agent": "BotBawel/1.0 (+https://discord.com)"}

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=headers) as client:
        for source_name, cat, feed_url in RSS_FEEDS:
            if category_filter and category_filter != "all" and cat != category_filter:
                continue
            try:
                resp = await client.get(feed_url)
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:max_per_feed]:
                    title = str(entry.get("title", "")).strip()
                    link = str(entry.get("link", "")).strip()
                    desc = str(entry.get("summary", "") or entry.get("description", "")).strip()
                    if title and link:
                        items.append(
                            RawNewsItem(
                                source=source_name,
                                category=cat,
                                title=title,
                                url=link,
                                summary_raw=desc[:600],
                                published_at=_parse_pubdate(entry),
                            )
                        )
            except Exception as e:
                logger.warning(f"Gagal ambil RSS {source_name}: {e}")

    return items


async def collect_and_store_new_news(ai_service, limit_new: int = 3) -> list[News]:
    """
    1. Ambil berita dari semua RSS feed
    2. Cek di PostgreSQL mana URL yang belum pernah disimpan (deduplikasi)
    3. Untuk berita baru (maks `limit_new` per siklus agar hemat kuota AI),
       minta AI merangkum & memberi label sentimen Bahasa Indonesia
    4. Simpan ke tabel `news` dan kembalikan untuk dipost ke Discord
    """
    raw_items = await fetch_rss_items(max_per_feed=5)
    if not raw_items:
        return []

    created_news: list[News] = []
    async with get_session() as session:
        urls = [item.url for item in raw_items]
        existing_urls = set(
            (await session.execute(select(News.url).where(News.url.in_(urls)))).scalars().all()
        )

        new_candidates = [it for it in raw_items if it.url not in existing_urls][:limit_new]
        for item in new_candidates:
            summary_id, sentiment, assets = await ai_service.summarize_news(
                title=item.title,
                snippet=item.summary_raw,
                source=item.source,
            )
            news_row = News(
                source=item.source,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                summary_id=summary_id,
                sentiment=sentiment,
                assets=assets,
                posted=False,
            )
            session.add(news_row)
            created_news.append(news_row)

        if created_news:
            await session.commit()
            for n in created_news:
                await session.refresh(n)

    return created_news
