# Polymarket BTC 5-Minute Signal Bot

Signal bot untuk market binary Polymarket "BTC Up or Down" (5 menit). Bot membaca harga BTC real-time dari Binance, menjalankan analisis teknikal + AI tiebreaker, lalu **mencetak sinyal UP/DOWN** sebelum window 5-menit Polymarket ditutup. Ini mode *no-wallet*: bot hanya memberi sinyal, TIDAK melakukan order.

---

## Cara Kerja

Setiap 5 menit Polymarket membuka market: "Akankah BTC lebih tinggi/rendah dari harga pembuka saat window ditutup?". Window mengikuti timestamp Unix yang habis dibagi 300.

```
window_ts     = now - (now % 300)          # mulai window
close_time    = window_ts + 300            # window tutup 5 menit kemudian
market slug   = btc-5m-{window_ts}
```

Bot tidur sampai **T-15s s/d T-1s** sebelum window ditutup (saat arah harga praktis terkunci), lalu menghitung sinyal dan mencetaknya.

---

## Arsitektur

| File         | Isi                                                               |
| ------------ | ----------------------------------------------------------------- |
| `signal.py`  | Semua logika: fetch data Binance, TA, AI tiebreaker, loop utama.  |

### Dependensi

```
requests>=2.31.0     # HTTP ke Binance + gateway AI
pandas               # manipulasi kline
python-dotenv>=1.0.0 # baca .env
```

---

## Strategi Sinyal

### 1. Window Delta (dominan)

Pertanyaan yang persis sama dengan market: "naik/turun vs harga buka window?".

```
delta = (current_price - window_open) / window_open * 100

> 0.10%  → skor ±7 (hampir pasti)
> 0.02%  → skor ±5 (kuat)
> 0.005% → skor ±3 (sedang)
> 0.001% → skor ±1 (tipis)
```

### 2. EMA 9

`current > EMA9` → skor +1, sebaliknya −1.

Total skor > 0 → **UP 🟢**, < 0 → **DOWN 🔴**. Confidence = `|skor|/8 × 100%`.

---

## AI Tiebreaker (optional)

Saat sinyal aturan lemah (`|score| <= 4`), bot bertanya ke model AI lewat endpoint OpenAI-compatible (mis. **9router / coding-fast**). AI menerima ringkasan: delta window, trend 1m/5m/15m, dan 12 close terakhir.

- Hasil AI menaikkan konfidensi (dibatasi maks 70%) dan bisa membalik arah.
- **Delta jendela tetap raja** — AI hanya dipakai saat aturan tidak yakin.
- Jika AI gagal / timeout / rate-limit, bot otomatis fallback ke sinyal aturan.

Konfigurasi di `.env`:

```env
AI_API_KEY=sk-...
AI_BASE_URL=https://ai-gateway.gylang.my.id/v1
AI_MODEL=coding-fast
```

---

## Output Contoh

```
[07:59:45] MARKET: btc-5m-1787702100 (07:55 PM-08:00 PM ET)
[07:59:45] SIGNAL: UP 🟢 (Conf: 75.0%) [AI]
[07:59:45] Prices: Open 78496.00 -> Cur 78510.00
[07:59:45] Chart  : █▇▇▆▆▆▅▅▄▄▄▅▆▄▅▅▆▆▅▅▅▄▄▄▄▃▃▃▂▂▂▁▂▁▁▁▂▂▂▂
--------------------------------------------------
```

- Waktu ET memakai `ZoneInfo("America/New_York")` → otomatis benar saat EDT (musim panas) maupun EST (musim dingin).
- `Chart:` adalah sparkline harga 40 menit terakhir (zero-dependency).

---

## Setup

1. Salin `.env.example` → `.env`:

```bash
cp .env.example .env
```

2. Isi `.env`:

```env
# Opsional: AI tiebreaker
AI_API_KEY=sk-...
AI_BASE_URL=https://ai-gateway.gylang.my.id/v1
AI_MODEL=coding-fast
```

> `.env` di-ignore oleh git. Jangan pernah commit isinya — mengandung secret.

3. Install dependensi:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Menjalankan

```bash
python signal.py
```

Atau via Docker:

```bash
docker compose up -d --build
```

---

## Troubleshooting

| Gejala                     | Solusi                                                    |
| -------------------------- | --------------------------------------------------------- |
| Semua Binance endpoint gagal | Gunakan `data-api.binance.vision` (mirror publik, sudah di fallback list). |
| `[AI] retry` di log        | Normal — model reasoning kadang timeout, bot otomatis retry sekali lalu fallback. |
| Waktu ET tidak pas         | Pastikan pakai Python 3.9+ (modul `zoneinfo` tersedia).   |

---

## Pelajaran Kunci

1. **Window delta adalah raja.** TA jangka pendek (EMA, RSI) sangat bising di skala 5 menit. Delta vs harga buka window adalah jawaban langsung atas pertanyaan market.
2. **Timing masuk itu segalanya.** T-15s s/d T-1s: cukup dekat agar arah terkunci, cukup jauh agar ada margin token.
3. **AI hanya pelengkap.** Jangan biarkan AI membalik sinyal saat delta sudah tegas — itu justru menambah noise.
4. **Rate limit Binance itu nyata.** Bot me-retry otomatis; kalau sering gagal, kurangi frekuensi fetch.
