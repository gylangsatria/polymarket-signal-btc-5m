# Tutorial: Polymarket BTC 5-Minute Signal Bot

Panduan lengkap setup, konfigurasi AI, dan menjalankan bot sinyal BTC Up/Down. Bot bisa dijalankan di **dua mode** (diatur `AUTO_TRADE` di `.env`):
- `AUTO_TRADE=false` → **SIGNAL-ONLY**: hanya memberi sinyal, tidak ada order/transaksi otomatis (mode default tutorial ini).
- `AUTO_TRADE=true` → **AUTO-TRADING**: prediksi + eksekusi order otomatis di Polymarket CLOB (strategi lengkap + FAQ: lihat [README.md](README.md)).

---

## 1. Apa yang Bot Ini Lakukan

1. Setiap window 5 menit Polymarket membuka market `btc-updown-5m-{window_ts}`.
2. Bot membaca kline 1-menit BTCUSDT dari Binance.
3. Bot memunculkan **tiga sinyal**: **URGENT** (jika delta >= 0.15% di awal), **PREDIKSI** di menit ke-2 window (T-180s), dan **KONFIRMASI** di T-60s sebelum tutup (1 menit terakhir):
   - Skor teknikal: **window delta** (dominant) + **EMA 9**.
   - Jika skor lemah (`|score| <= 4`), bot bertanya ke **AI** (9router/coding-fast) sebagai tiebreaker.
4. Mencetak arah + confidence + sparkline chart ke terminal.

---

## 2. Prasyarat

- Python 3.9+ (wajib untuk modul `zoneinfo`).
- Akses internet ke `data-api.binance.vision` (atau api Binance lainnya).
- (Opsional) API key AI — mis. dari **9router** dengan model `coding-fast` dan base URL `https://api.your-gateway.example/v1`.
- (Optional) Docker + Docker Compose untuk menjalankan via container.

---

## 3. Setup

### 3.1 Clone / Salin Project

```bash
git clone <repo-anda>/PolymarketBot.git
cd PolymarketBot
```

### 3.2 Buat .env

```bash
cp .env.example .env
```

Isi `.env`:

```env
# AI API (9router / coding-fast)
AI_API_KEY=sk-...ganti-dengan-api-key-anda...
AI_BASE_URL=https://api.your-gateway.example/v1
AI_MODEL=coding-fast
```

> `.env` sudah masuk `.gitignore`. Jangan pernah commit file ini — API key adalah secret.
>
> Tanpa `AI_API_KEY`, bot tetap jalan menggunakan sinyal aturan saja (AI dinonaktifkan).

### 3.3 Install Dependensi

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 4. Menjalankan

### Cara A — Langsung dengan Python

```bash
python signal.py
```

### Cara B — Docker

```bash
docker compose up -d --build
```

> **Ubah pengaturan interaktif:** `python3 config.py` — menu pilih parameter → isi nilai → simpan ke `.env` → restart otomatis. Semua nilai tersimpan di `.env`.

Lihat log:

```bash
docker compose logs -f signal
```

Berhenti:

```bash
docker compose down
```

---

## 5. Membaca Output

```
[07:59:45] MARKET: btc-updown-5m-1787702100 (07:55 PM-08:00 PM ET)
[07:59:45] PREDIKSI: UP ������ (Prob: 75.0%) [aturan]
[07:59:45] Prices: Open 78496.00 -> Cur 78510.00
[07:59:45] Chart  : █▇▇▆▆▆▅▅▄▄▄▅▆▄▅▅▆▆▅▅▅▄▄▄▃▃▃▁▁▁▁▁▁▁▁▁▁▁▁
--------------------------------------------------
```

| Baris      | Arti                                                              |
| ---------- | ----------------------------------------------------------------- |
| `MARKET`   | Slug market dan rentang waktu window dalam ET (auto DST).         |
| `PREDIKSI` | Arah prediksi + probabilitas (win rate empiris / aturan / AI).    |
| `Prices`   | Harga buka window vs harga terkini.                               |
| `Chart`    | Sparkline 40 menit terakhir (kanan = terkini).                    |

Urutan sinyal per window: **URGENT** (delta ≥ 0.15% di 1 menit awal, opsional), **PREDIKSI** (menit ke-2, T-180s), **KONFIRMASI** (T-60s, 1 menit terakhir — keputusan final).

---

## 6. Cara Kerja Sinyal

### Skor Aturan

```python
# Window delta: menjawab langsung pertanyaan market
delta = (cur - open) / open * 100
# |delta| > 0.10% -> ±7 | > 0.02% -> ±5 | > 0.005% -> ±3 | > 0.001% -> ±1

# EMA 9
if cur > ema9: score += 1
else:          score -= 1
```

### AI Tiebreaker

- Dipanggil hanya jika `|score| <= 4` (aturan belum yakin).
- Kirim ringkasan ringkas (delta, trend 1m/5m/15m, 12 close terakhir) — prompt panjang membuat model reasoning (`deepseek-v4-flash`) kehabisan token dan mengembalikan jawaban kosong.
- AI dibatasi mempengaruhi confidence maksimal 70%.
- Gagal/timeout → retry 1× → fallback ke sinyal aturan. Bot tidak pernah berhenti.

### Anti-whipsaw

KONFIRMASI (T-60s, 1 menit terakhir) **tidak langsung membalik arah** PREDIKSI: jika arah baru berlawanan tapi `|delta| < 0.03%`, arah ditahan (`[HOLD]`, confidence ≤ 40%). Harga yang nyaris menyentuh open bisa bolak-balik — flip hanya jika pembalikan tegas (≥ 0.03%).

---

## 7. Waktu & Zona (Penting)

- Polymarket menggunakan timestamp Unix yang habis dibagi 300 sebagai slug market.
- Konversi ke ET memakai `ZoneInfo("America/New_York")` — **otomatis** menangani DST:
  - Agustus (musim panas): EDT = UTC−4.
  - Desember (musim dingin): EST = UTC−5.
- Contoh verifikasi: window `1787702100` = **Aug 25, 07:55 PM — 08:00 PM ET**.