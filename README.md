# 🗣️ BotBawel — Personal Trading & Economic News Discord Bot

Asisten market pribadi di Discord untuk **Crypto (`BTC/USDT`, `ETH/USDT`)** & **Gold (`XAU/USD`)** dengan analisis teknikal multi-timeframe (`15m`, `30m`, `1h`), kalender ekonomi (CPI, NFP, FOMC), ringkasan berita AI (Bahasa Indonesia), price alert, dan briefing otomatis 2x sehari (`07:00` & `19:00` WIB).

---

## 🚀 Cara Menjalankan

1. Pastikan database PostgreSQL **`botbawel`** sudah dibuat di DBeaver.
2. Pastikan file `.env` sudah terisi minimal:
   ```env
   DISCORD_TOKEN=token_bot_discord_kamu
   DISCORD_GUILD_ID=id_server_discord_kamu
   DATABASE_URL=postgresql+asyncpg://postgres:password_kamu@localhost:5432/botbawel
   GEMINI_API_KEY=opsional_bisa_diisi_nanti
   TWELVEDATA_API_KEY=opsional_bisa_diisi_nanti
   ```
3. Jalankan bot:
   ```powershell
   & "D:\.vscode\kodingan\NewsBot - BotBawel\.venv\Scripts\python.exe" "D:\.vscode\kodingan\NewsBot - BotBawel\bot\main.py"
   ```

---

## 💬 Daftar Slash Commands

| Command | Fungsi |
|---|---|
| `/ping` | Cek status bot, latensi gateway, & status AI |
| `/price <symbol>` | Cek harga terkini, perubahan 24 jam, High/Low (`BTC`, `ETH`, `XAUUSD`) |
| `/watchlist list` | Lihat semua aset di watchlist beserta harganya |
| `/watchlist add <symbol>` | Tambah aset ke watchlist |
| `/watchlist remove <symbol>` | Hapus aset dari watchlist |
| `/news [refresh]` | Tampilkan 3 berita terbaru + ringkasan & sentimen AI Bahasa Indonesia |
| `/calendar [today\|week]` | Jadwal kalender ekonomi High/Medium impact dalam waktu WIB |
| `/alert add <symbol> <above\|below> <price>` | Pasang alarm harga otomatis |
| `/alert list` / `/alert remove <id>` | Lihat / hapus alarm harga |
| `/analyze <symbol> [15m\|30m\|1h]` | Analisis EMA 5/20, RSI 14 + MA RSI, Support/Resistance, & Konfluensi 15m-30m-1h |
| `/scan` | Pindai seluruh watchlist sekarang juga |
| `/briefing` | Minta rangkuman pasar lengkap (harga + berita AI + kalender ekonomi) kapan saja |
