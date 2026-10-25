"""
bot/services/ai.py
------------------
Layanan AI menggunakan Google Gemini API (`google-genai`) untuk:
1. Merangkum berita 2-3 kalimat dalam Bahasa Indonesia + menentukan sentimen (Bullish/Bearish/Netral)
   serta aset yang terdampak.
2. Menyusun Daily Briefing (Pagi 07:00 WIB, Malam 19:00 WIB, atau Manual) berdasarkan harga,
   berita terbaru, dan agenda kalender ekonomi.

Model: `models/gemini-3.8-flash` (dengan auto-fallback ke `gemini-3-flash-preview`).
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

CANDIDATE_MODELS = [
    "models/gemini-3.8-flash",
    "models/gemini-3-flash-preview",
    "models/gemini-flash-latest",
]


class AIService:
    """Wrapper Gemini AI untuk analisis berita & pembuatan briefing berbahasa Indonesia."""

    def __init__(self, api_key: str | None, model_name: str = "models/gemini-3.8-flash") -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key) if (api_key and genai) else None

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    async def _generate_text(self, prompt: str) -> str | None:
        if not self._client:
            return None

        # Coba model utama, jika gagal coba kandidat model lainnya
        models_to_try = [self.model_name] + [m for m in CANDIDATE_MODELS if m != self.model_name]

        for model in models_to_try:
            try:
                resp = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=model,
                    contents=prompt,
                )
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                logger.warning(f"Gemini API model {model} gagal: {e}")
                continue

        return None

    async def summarize_news(
        self, title: str, snippet: str, source: str
    ) -> tuple[str, str, str]:
        """
        Kembalikan tuple: (ringkasan_indonesia, sentimen, aset_terdampak).
        Sentimen bernilai salah satu dari: "Bullish", "Bearish", atau "Netral".
        """
        prompt = (
            "Kamu adalah analis pasar finansial senior untuk Crypto, Emas (XAU/USD), dan Makroekonomi global.\n"
            "Tugasmu: baca berita berikut, lalu buat kesimpulan dalam Bahasa Indonesia.\n"
            "Tentukan sentimen terhadap pasar/aset terkait secara tegas:\n"
            "- Bullish: jika berita membawa sentimen positif, adopsi naik, inflow, stimulus, penurunan suku bunga, atau potensi kenaikan harga.\n"
            "- Bearish: jika berita membawa risiko, penurunan harga, outflow, regulasi ketat, perang/konflik, atau kenaikan suku bunga.\n"
            "- Netral: hanya jika berita benar-benar murni informatif tanpa arah dampak.\n\n"
            "Balas HANYA dalam JSON valid tanpa markdown tambahan dengan format:\n"
            '{"summary": "Ringkasan 2-3 kalimat padat Bahasa Indonesia", '
            '"sentiment": "Bullish atau Bearish atau Netral", '
            '"assets": "Simbol aset relevan (contoh: BTC, ETH, XAU/USD, USD)"}\n\n'
            f"Sumber: {source}\n"
            f"Judul: {title}\n"
            f"Isi: {snippet}\n"
        )
        raw = await self._generate_text(prompt)
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
            except Exception as e:
                logger.warning(f"Gagal parse JSON Gemini: {e} | Raw: {raw[:150]}")

        # Fallback jika tidak ada respon AI
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
            "Kamu adalah BotBawel, asisten trading pribadi yang cerdas, tajam, ringkas, dan to-the-point.\n"
            f"Buat rangkuman pasar ({kind}) dalam Bahasa Indonesia yang profesional dan mudah dibaca menggunakan formatting Discord (bold, bullet point, emoji).\n\n"
            "Struktur rangkuman:\n"
            "1. 📊 **Sorotan Pasar Hari Ini**: Jelaskan kondisi BTC, ETH, dan Emas (XAU/USD) secara komprehensif berdasarkan data harga.\n"
            "2. 📰 **Intisari Berita & Katalis Sentimen**: Jelaskan apa yang sedang menggerakkan pasar dari berita terbaru.\n"
            "3. 📅 **Waspada Kalender Ekonomi**: Agenda ekonomi yang perlu diantisipasi trader timeframe 15m-1h (dalam WIB).\n"
            "4. 💡 **Catatan Manajemen Risiko**: 1 kalimat penutup pengingat disiplin risiko (bukan nasihat finansial).\n\n"
            f"=== DATA HARGA ===\n{tickers_block}\n\n"
            f"=== BERITA TERBARU ===\n{news_block}\n\n"
            f"=== AGENDA EKONOMI ===\n{events_block}\n"
        )

        ai_text = await self._generate_text(prompt)
        if ai_text:
            return ai_text

        # Fallback rapi bila koneksi gagal
        return (
            f"📊 **Ringkasan Watchlist**\n{tickers_block}\n\n"
            f"📰 **Berita Terbaru**\n{news_block}\n\n"
            f"📅 **Agenda Ekonomi Terdekat**\n{events_block}\n\n"
            "_Catatan: Terjadi kendala saat menghubungkan ke AI Gemini._"
        )
