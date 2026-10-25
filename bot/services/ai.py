"""
bot/services/ai.py
------------------
Layanan AI menggunakan Google Gemini API (`google-genai`).
Model: `models/gemini-3.8-flash` (cepat, hemat kuota, dan responsif).
Dilengkapi timeout 10 detik agar tidak pernah menggantung (hang).
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
    """Wrapper Gemini AI untuk analisis berita & briefing pasar berbahasa Indonesia."""

    def __init__(self, api_key: str | None, model_name: str = "models/gemini-3.8-flash") -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key) if (api_key and genai) else None

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    async def _generate_text(self, prompt: str, timeout_sec: float = 12.0) -> str | None:
        if not self._client:
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
            logger.warning(f"Gemini API timeout setelah {timeout_sec} detik.")
            return None
        except Exception as e:
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
            "Kamu adalah analis pasar finansial senior untuk Crypto, Emas (XAU/USD), dan Makroekonomi.\n"
            "Tugas: baca berita berikut, buat ringkasan padat 2 kalimat dalam Bahasa Indonesia dan tentukan sentimennya.\n"
            "Sentimen harus tegas:\n"
            "- Bullish: jika membawa dampak positif, inflow, kenaikan harga, pemangkasan suku bunga, atau adopsi.\n"
            "- Bearish: jika membawa risiko, outflow, penurunan harga, ketegangan geopolitik/perang, atau kenaikan suku bunga.\n"
            "- Netral: hanya jika berita tidak berdampak ke arah pasar.\n\n"
            "Balas HANYA dalam JSON valid tanpa markdown tambahan dengan struktur:\n"
            '{"summary": "Ringkasan 2 kalimat Bahasa Indonesia", '
            '"sentiment": "Bullish atau Bearish atau Netral", '
            '"assets": "Simbol aset relevan (contoh: BTC, ETH, XAU/USD, USD)"}\n\n'
            f"Sumber: {source}\n"
            f"Judul: {title}\n"
            f"Cuplikan: {snippet[:400]}\n"
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
            except Exception as e:
                logger.warning(f"Gagal parse JSON Gemini: {e}")

        # Fallback cepat bila offline/timeout
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
            "Struktur:\n"
            "1. 📊 **Sorotan Pasar**: Analisis kondisi BTC, ETH, dan Emas (XAU/USD) berdasarkan data harga.\n"
            "2. 📰 **Intisari Berita**: Sentimen & katalis penggerak pasar utama.\n"
            "3. 📅 **Waspada Kalender Ekonomi**: Jadwal penting terdekat (WIB).\n"
            "4. 💡 **Catatan Disiplin**: 1 kalimat penutup pengingat manajemen risiko.\n\n"
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
