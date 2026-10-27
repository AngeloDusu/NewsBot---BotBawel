"""
bot/services/ai.py
------------------
Layanan AI menggunakan Google Gemini API (`google-genai`).
Model Utama: `models/gemini-flash-lite-latest` (kuota Free Tier lebih besar, cepat, dan hemat token).
Dilengkapi penanganan 429 RESOURCE_EXHAUSTED yang elegan (otomatis fallback ke rule-based tanpa crash).
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

# Model ringan dengan kuota harian besar di Free Tier
DEFAULT_MODEL = "models/gemini-flash-lite-latest"


class AIService:
    """Wrapper Gemini AI untuk analisis berita & briefing pasar berbahasa Indonesia."""

    def __init__(self, api_key: str | None, model_name: str = DEFAULT_MODEL) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key) if (api_key and genai) else None
        self._rate_limited_until: float = 0.0

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    async def _generate_text(self, prompt: str, timeout_sec: float = 12.0) -> str | None:
        if not self._client:
            return None

        # Jika sebelumnya terkena 429, hindari spamming API dan gunakan fallback
        import time
        if time.time() < self._rate_limited_until:
            return None

        def _call_api() -> str:
            resp = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return (resp.text or "").strip()

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call_api), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning(f"Gemini API timeout ({timeout_sec}s). Menggunakan fallback.")
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logger.warning("Gemini API kuota harian tercapai (429). Beralih ke fallback analisis lokal.")
                # Istirahatkan request AI selama 30 menit
                self._rate_limited_until = time.time() + 1800
            elif "503" in err_str:
                logger.warning("Gemini API server sedang sibuk (503). Menggunakan fallback.")
            else:
                logger.warning(f"Gemini API error: {e}")
            return None

    async def summarize_news(
        self, title: str, snippet: str, source: str
    ) -> tuple[str, str, str]:
        """
        Kembalikan tuple: (ringkasan_indonesia, sentimen, aset_terdampak).
        Sentimen bernilai: "Bullish", "Bearish", atau "Netral".
        """
        prompt = (
            "Kamu analis pasar profesional Crypto, Emas (XAU/USD), dan Makroekonomi.\n"
            "Baca berita berikut, buat ringkasan 2 kalimat Bahasa Indonesia dan tentukan sentimennya.\n"
            "Ketentuan sentimen:\n"
            "- Bullish: jika positif, inflow, adopsi, kenaikan harga, pemangkasan suku bunga.\n"
            "- Bearish: jika negatif, outflow, penurunan harga, risiko perang/konflik, suku bunga naik.\n"
            "- Netral: jika murni informasi tanpa arah dampak pasar.\n\n"
            "Balas HANYA JSON valid:\n"
            '{"summary": "Ringkasan 2 kalimat", "sentiment": "Bullish|Bearish|Netral", "assets": "BTC, ETH, XAU/USD, dll"}\n\n'
            f"Judul: {title}\n"
            f"Isi: {snippet[:350]}\n"
        )
        raw = await self._generate_text(prompt, timeout_sec=10.0)
        if raw:
            try:
                clean_json = raw.strip()
                if clean_json.startswith("```"):
                    clean_json = re.sub(r"^```[a-zA-Z]*\n?", "", clean_json)
                    clean_json = re.sub(r"\n?```$", "", clean_json)
                match = re.search(r"\{.*\}", clean_json, re.DOTALL)
                payload = json.loads(match.group(0) if match else clean_json)
                summary = str(payload.get("summary") or title).strip()
                sentiment = str(payload.get("sentiment") or "Netral").capitalize()
                if sentiment not in {"Bullish", "Bearish", "Netral"}:
                    sentiment = "Netral"
                assets = str(payload.get("assets") or "Market").strip()
                return summary, sentiment, assets
            except Exception:
                pass

        # Fallback lokal jika kuota AI sedang penuh
        text_lower = f"{title} {snippet}".lower()
        bullish_kw = ("surge", "jump", "rally", "bull", "gain", "soar", "approve", "cut rate", "inflow", "buying", "high")
        bearish_kw = ("drop", "crash", "fall", "bear", "plunge", "hack", "lawsuit", "hike", "outflow", "pressure", "slide", "evacuation")

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
            "Kamu adalah BotBawel, asisten trading pribadi yang cerdas dan ringkas.\n"
            f"Buat rangkuman pasar ({kind}) dalam Bahasa Indonesia menggunakan format Discord yang rapi:\n\n"
            "Struktur:\n"
            "1. 📊 **Sorotan Pasar**: Kondisi BTC, ETH, dan XAU/USD berdasarkan harga saat ini.\n"
            "2. 📰 **Intisari Berita**: Sentimen utama penggerak pasar.\n"
            "3. 📅 **Kalender Ekonomi**: Agenda penting terdekat (WIB).\n"
            "4. 💡 **Catatan Risiko**: 1 kalimat pengingat disiplin trading.\n\n"
            f"=== DATA HARGA ===\n{tickers_block}\n\n"
            f"=== BERITA TERBARU ===\n{news_block}\n\n"
            f"=== AGENDA EKONOMI ===\n{events_block}\n"
        )

        ai_text = await self._generate_text(prompt, timeout_sec=15.0)
        if ai_text:
            return ai_text

        return (
            f"📊 **Ringkasan Watchlist**\n{tickers_block}\n\n"
            f"📰 **Berita Terbaru**\n{news_block}\n\n"
            f"📅 **Agenda Ekonomi Terdekat**\n{events_block}\n"
        )
