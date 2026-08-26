# Tutorial: Polymarket BTC 5-Minute Signal Bot

Panduan lengkap setup, konfigurasi AI, dan menjalankan bot sinyal BTC Up/Down (mode no-wallet). Bot ini **hanya memberi sinyal** — tidak ada order/transaksi otomatis.

---

## 1. Apa yang Bot Ini Lakukan

1. Setiap window 5 menit Polymarket membuka market `btc-5m-{window_ts}`.
2. Bot membaca kline 1-menit BTCUSDT dari Binance.
3. Bot memunculkan **2 sinyal**: **PREDIKSI** di menit ke-2 window (T-180s) dan **KONFIRMASI** di T-110s sebelum tutup (1 menit 50 detik terakhir):
   - Skor teknikal: **window delta** (dominant) + **EMA 9**.
   - Jika skor lemah (`|score| <= 4`), bot bertanya ke **AI** (9router/coding-fast) sebagai tiebreaker.
4. Mencetak arah + confidence + sparkline chart ke terminal.

---

## 2. Prasyarat

- Python 3.9+ (wajib untuk modul `zoneinfo`).
- Akses internet ke `data-api.binance.vision` (atau api Binance lainnya).
- (Opsional) API key AI — mis. dari **9router** dengan model `coding-fast` dan base URL `https://ai-gateway.gylang.my.id/v1`.
- (Opsional) Docker + Docker Compose untuk menjalankan via container.

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
AI_BASE_URL=https://ai-gateway.gylang.my.id/v1
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
[07:59:45] MARKET: btc-5m-1787702100 (07:55 PM-08:00 PM ET)
[07:59:45] SIGNAL: UP 🟢 (Conf: 75.0%) [AI]
[07:59:45] Prices: Open 78496.00 -> Cur 78510.00
[07:59:45] Chart  : █▇▇▆▆▆▅▅▄▄▄▅▆▄▅▅▆▆▅▅▅▄▄▄▃▃▃▂▂▂▁▂▁▁▁▂▂▂▂
--------------------------------------------------
```

| Baris      | Arti                                                              |
| ---------- | ----------------------------------------------------------------- |
| `MARKET`   | Slug market dan rentang waktu window dalam ET (auto DST).         |
| `SIGNAL`   | Arah prediksi + confidence. Tanda `[AI]` = keputusan dibantu AI.  |
| `Prices`   | Harga buka window vs harga terkini.                               |
| `Chart`    | Sparkline 40 menit terakhir (kanan = terkini).                    |

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

KONFIRMASI (T-110s, 1m50s terakhir) **tidak langsung membalik arah** PREDIKSI: jika arah baru berlawanan tapi `|delta| < 0.03%`, arah ditahan (`[HOLD]`, confidence ≤ 40%). Harga yang nyaris menyentuh open bisa bolak-balik — flip hanya jika pembalikan tegas (≥ 0.03%).

---

## 7. Waktu & Zona (Penting)

- Polymarket menggunakan timestamp Unix yang habis dibagi 300 sebagai slug market.
- Konversi ke ET memakai `ZoneInfo("America/New_York")` — **otomatis** menangani DST:
  - Agustus (musim panas): EDT = UTC−4.
  - Desember (musim dingin): EST = UTC−5.
- Contoh verifikasi: window `1787702100` = **Aug 25, 07:55 PM − 08:00 PM ET**.

---

## 8. Troubleshooting

| Gejala                     | Solusi                                                                       |
| -------------------------- | ---------------------------------------------------------------------------- |
| `Failed: api.binance.com`  | Jaringan memblokir domain itu. Bot memakai mirror `data-api.binance.vision` yang kini **urutan pertama** — tidak ada lagi log error di operasi normal. |
| `[AI] retry` di log        | Model reasoning timeout/kehabisan token — bot retry sekali lalu fallback.    |
| `[AI] skipped` terus       | Cek `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` di `.env`. Atau matikan AI dengan mengosongkan `AI_API_KEY`. |
| `ModuleNotFoundError: zoneinfo` | Pakai Python 3.9+ atau `pip install tzdata`.                                  |
| Sinyal tidak pernah muncul  | Loop menunggu `time_into_window >= 120` (PREDIKSI) / `>= 190` (KONFIRMASI, T-110s). Cek log di menit ke-2 dan 1m50s terakhir. |

---

## 9. Tips

1. **AI bukan pengganti delta window.** Saat delta sudah tegas (> 0.10%), aturan menang — jangan paksa AI membaliknya.
2. **Gunakan API key yang sesuai.** Base URL gateway menentukan model; pastikan `AI_MODEL` valid di gateway Anda (mis. 9router `coding-fast`).
3. **Amati beberapa window dulu.** Catat akurasi sinyal vs hasil aktual sebelum mengintegrasikan ke bot trading sungguhan.
4. **Jaga log.** Redirect output ke file bila menjalankan di background: `python signal.py >> signal.log 2>&1`.
