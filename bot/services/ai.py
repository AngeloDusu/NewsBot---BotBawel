"""
bot/services/ai.py
------------------
Layanan AI menggunakan Google Gemini API (`google-genai`) untuk:
1. Merangkum berita 2-3 kalimat dalam Bahasa Indonesia + menentukan sentimen (Bullish/Bearish/Netral)
   serta aset yang terdampak.
2. Menyusun Daily Briefing (Pagi 07:00 WIB, Malam 19:00 WIB, atau Manual) berdasarkan harga,
   berita terbaru, dan agenda kalender ekonomi.

Dilengkapi fallback otomatis apabila `GEMINI_API_KEY` belum diisi di `.env`, sehingga bot
tetap berjalan normal kapan saja.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Iterable

from loguru import logger

try:
    from google import genai
except Exception:
    genai = None  # type: ignore


class AIService:
    """Wrapper Gemini AI untuk analisis berita & pembuatan briefing berbahasa Indonesia."""

    def __init__(self, api_key: str | None, model_name: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key) if (api_key and genai) else None

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    async def _generate_text(self, prompt: str) -> str | None:
        if not self._client:
            return None
        try:
            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model_name,
                contents=prompt,
            )
            return (resp.text or "").strip()
        except Exception as e:
            logger.warning(f"Gemini API gagal dipanggil: {e}")
            return None

    async def summarize_news(
        self, title: str, snippet: str, source: str
    ) -> tuple[str, str, str]:
        """
        Kembalikan tuple: (ringkasan_indonesia, sentimen, aset_terdampak).
        Sentimen bernilai salah satu dari: "Bullish", "Bearish", atau "Netral".
        """
        prompt = (
            "Kamu adalah analis pasar crypto, emas (XAU/USD), dan makroekonomi.\n"
            "Baca berita berikut dan balas HANYA dalam format JSON valid dengan key:\n"
            '{"summary": "ringkasan 2-3 kalimat bahasa Indonesia yang padat dan jelas", '
            '"sentiment": "Bullish atau Bearish atau Netral", '
            '"assets": "daftar singkat simbol terdampak, mis. BTC, ETH, XAU/USD, USD"}\n\n'
            f"Sumber: {source}\n"
            f"Judul: {title}\n"
            f"Isi singkat: {snippet}\n"
        )
        raw = await self._generate_text(prompt)
        if raw:
            try:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                payload = json.loads(match.group(0) if match else raw)
                summary = str(payload.get("summary") or title).strip()
                sentiment = str(payload.get("sentiment") or "Netral").capitalize()
                if sentiment not in {"Bullish", "Bearish", "Netral"}:
                    sentiment = "Netral"
                assets = str(payload.get("assets") or "Market").strip()
                return summary, sentiment, assets
            except Exception:
                pass

        # Fallback rule-based jika Gemini belum aktif / gagal parse
        text_lower = f"{title} {snippet}".lower()
        bullish_kw = ("surge", "jump", "rally", "bull", "gain", "soar", "approve", "cut rate", "inflow")
        bearish_kw = ("drop", "crash", "fall", "bear", "plunge", "hack", "lawsuit", "hike", "outflow")

        if any(k in text_lower for k in bullish_kw):
            sentiment = "Bullish"
        elif any(k in text_lower for k in bearish_kw):
            sentiment = "Bearish"
        else:
            sentiment = "Netral"

        assets_found: list[str] = []
        for sym, kw in [("BTC", "bitcoin"), ("ETH", "ethereum"), ("XAU/USD", "gold"), ("USD", "fed")]:
            if kw in text_lower or sym.lower() in text_lower:
                assets_found.append(sym)
        assets_str = ", ".join(assets_found) if assets_found else "Crypto / Macro"
        clean_snip = re.sub(r"<[^>]+>", "", snippet).strip()
        summary_fallback = clean_snip[:240] + ("..." if len(clean_snip) > 240 else "")
        return (summary_fallback or title), sentiment, assets_str

    async def generate_briefing(
        self,
        kind: str,
        tickers_summary: Iterable[str],
        news_summary: Iterable[str],
        events_summary: Iterable[str],
    ) -> str:
        """Buat narasi briefing pasar dalam Bahasa Indonesia."""
        tickers_block = "\n".join(tickers_summary) or "- Belum ada data harga."
        news_block = "\n".join(news_summary) or "- Belum ada berita baru."
        events_block = "\n".join(events_summary) or "- Tidak ada jadwal ekonomi High/Medium terdekat."

        prompt = (
            "Kamu adalah BotBawel, asisten trading pribadi yang cerdas, ringkas, dan to-the-point.\n"
            f"Buat rangkuman pasar ({kind}) dalam Bahasa Indonesia menggunakan bullet points yang rapi.\n"
            "Struktur:\n"
            "1. Kondisi Harga Watchlist (BTC, ETH, XAU/USD)\n"
            "2. Intisari Berita & Sentimen Pasar\n"
            "3. Agenda Kalender Ekonomi Penting (WIB) & hal yang perlu diwaspadai trader timeframe 15m-1h\n"
            "Akhiri dengan pengingat singkat manajemen risiko (bukan nasihat finansial).\n\n"
            f"=== DATA HARGA ===\n{tickers_block}\n\n"
            f"=== BERITA TERBARU ===\n{news_block}\n\n"
            f"=== AGENDA EKONOMI ===\n{events_block}\n"
        )

        ai_text = await self._generate_text(prompt)
        if ai_text:
            return ai_text

        # Fallback rapi bila tanpa API key Gemini
        return (
            f"📊 **Ringkasan Watchlist**\n{tickers_block}\n\n"
            f"📰 **Berita Terbaru**\n{news_block}\n\n"
            f"📅 **Agenda Ekonomi Terdekat**\n{events_block}\n\n"
            "_Catatan: Isi `GEMINI_API_KEY` di `.env` untuk mengaktifkan narasi analisis AI otomatis._"
        )
