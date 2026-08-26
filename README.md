# Polymarket BTC 5-Minute Signal Bot

Signal bot untuk market binary Polymarket "BTC Up or Down" (5 menit). Bot membaca harga BTC real-time dari Binance, menjalankan analisis teknikal + AI tiebreaker, lalu **mencetak sinyal UP/DOWN** sebelum window 5-menit Polymarket ditutup. Dengan `AUTO_TRADE=true`, sinyal KONFIRMASI (keputusan final) **langsung dieksekusi sebagai market order di Polymarket CLOB** — dana USDC & posisi tetap sebagai collateral di Polymarket, **tidak pernah ditarik ke wallet eksternal**.

---

## Cara Kerja

Setiap 5 menit Polymarket membuka market: "Akankah BTC lebih tinggi/rendah dari harga pembuka saat window ditutup?". Window mengikuti timestamp Unix yang habis dibagi 300.

```
window_ts     = now - (now % 300)          # mulai window
close_time    = window_ts + 300            # window tutup 5 menit kemudian
market slug   = btc-updown-5m-{window_ts}   # diverifikasi dari gamma-api
```

Bot memunculkan **tiga sinyal per window**: **URGENT** (jika delta >= 0.15% di 1 menit awal), **PREDIKSI** di menit ke-2 (T-180s), lalu **KONFIRMASI** di T-60s (1 menit terakhir) sebelum tutup. Setelah tutup, bot **memverifikasi hasil** — win rate empiris dipakai sebagai probabilitas (kalibrasi per bucket delta).

---

## Arsitektur

| File         | Isi                                                               |
| ------------ | ----------------------------------------------------------------- |
| `signal.py`  | Semua logika: fetch data Binance, TA, AI tiebreaker, loop utama, hook auto-trade. |
| `trader.py`  | Auto-trader CLOB Polymarket via SDK resmi `polymarket-client` (auth, lookup market, market order FOK). |

### Dependensi

```
requests>=2.31.0     # HTTP ke Binance + gateway AI
pandas               # manipulasi kline
python-dotenv>=1.0.0 # baca .env
polymarket-client    # SDK resmi Polymarket CLOB (auto-trade)
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

Total skor > 0 → **UP 🟢**, < 0 → **DOWN 🔴**. Confidence = `|skor|/8 × 100%`, **dibatasi maks 80%** — prediksi 1 menit tidak pernah layak klaim 100%.

**Anti-whipsaw (HOLD):** jika KONFIRMASI (T-60s) berubah arah tapi `|delta| < 0.03%` (harga nyaris di open), arah **ditahan** mengikuti PREDIKSI dan confidence dibatasi 40%. Pembalikan tipis sering noise yang bisa balik lagi; flip hanya jika delta berlawanan **tegas** (≥ 0.03%).

---

## Akurasi & Verifikasi

- Setelah window tutup, bot **memverifikasi** prediksi vs harga close aktual (`VERIFY: ... BENAR/SALAH`) dan menyimpan riwayat di `stats.json`.
- Probabilitas yang dicetak = **win rate empiris** per bucket `|delta|` (tegas/kuat/sedang/tipis) setelah ≥ 15 sampel. Sebelum cukup sampel, memakai skor aturan (cap 80%).
- `[HOLD]` di KONFIRMASI = arah PREDIKSI dipertahankan karena pembalikan tipis (< 0.03%) dianggap noise.
- Mulai fresh: hapus `stats.json`. Riwayat menumpuk antar-restart.

```
[07:57:12] PREDIKSI: UP 🟢 (Prob: 62.3%) [empirik-tegas (18 sampel)]
[07:59:32] KONFIRMASI: UP 🟢 (Prob: 64.7%) [empirik-tegas (18 sampel)]
[08:00:12] VERIFY: btc-updown-5m-1787702100 BENAR (close 78510.00 vs open 78496.00) | win rate 61.1% (11/18)
```

- Probabilitas dikalibrasi dari **hasil sinyal KONFIRMASI** (T-60s) — keputusan final.
- `URGENT` (Delta >= 0.15% di 1 menit awal) untuk entry sangat cepat; `PREDIKSI` (T-180s) untuk aksi awal; `KONFIRMASI` (T-60s, 1 menit terakhir) untuk memastikan.

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

## Dua Mode Aplikasi (dari `.env`)

| `AUTO_TRADE` | Mode | Perilaku |
|---|---|---|
| `false` | **SIGNAL-ONLY** | Bot hanya memantau & mencetak prediksi UP/DOWN + probabilitas — **tidak ada order** |
| `true` | **AUTO-TRADING** | Bot memprediksi **dan** langsung eksekusi order di Polymarket CLOB (`TRADE_AMOUNT_USD` per window) |

Ubah di `.env` lalu `docker compose up -d` (tanpa rebuild). Di log, judul bot menunjukkan mode aktif: `[AUTO-TRADE, $1.00/window]` = auto-trading, `[signal-only]` = sinyal saja.

---

## Auto-Trade (CLOB Polymarket)

Saat `AUTO_TRADE=true`, bot mengeksekusi **satu market order per window** di CLOB Polymarket lewat SDK resmi `polymarket-client`:

- **Sinyal UP** → beli token **Up** (`btc-updown-5m-{window}`), **sinyal DOWN** → beli token **Down**.
- Eksekusi di **PREDIKSI** (menit ke-2, T-180s) saat harga masih wajar; skip otomatis bila best ask > `TRADE_MAX_ASK` (default 0.6) atau tidak ada likuiditas. KONFIRMASI (T-60s) jadi fallback bila belum ada order. Dengan `TRADE_ON_URGENT=true`, sinyal URGENT juga langsung dieksekusi.
- Order memakai `FOK` (fill-or-kill): modal yang tidak terisi penuh di book dibatalkan, tidak ada posisi parsial yang menggantung.
- **Mode agresif** (`TRADE_AGGRESSIVE=true`): jika probabilitas prediksi ≥ `TRADE_MIN_PROB` (default 60, persen) → langsung FOK, **lewati** guard `TRADE_MAX_ASK` (baik arah UP maupun DOWN). Guard harga hanya aktif saat probabilitas di bawah ambang.
- **Recheck**: selama belum ada order dan belum KONFIRMASI, bot mengecek ulang probabilitas tiap 15 detik — begitu naik ke ≥ `TRADE_MIN_PROB`, langsung eksekusi tanpa menunggu menit terakhir.
- **Take-profit & cut-loss**: setelah posisi terbentuk, bot cek best bid tiap 15 detik. Jika ROI ≥ `SELL_ROI_MIN` (10%) → jual FOK, kunci profit lalu **berhenti di window itu** (tunggu market berikutnya; set `STOP_AFTER_TAKE_PROFIT=false` untuk mengembalikan perilaku lama: bisa beli lagi / scalping dalam 1 window). Jika bid ≤ `SELL_CUT_LOSS` (0.25) → jual FOK, ambil sisa nilai, **dan berhenti entry di window itu** (1 rugi per window cukup). **Jeda cut-loss**: < `SELL_CUT_LOSS_MIN_ELAPSED` (90s) sejak entry, bot HOLD — window 5m volatil di menit 1-2, harga bisa menyapu 0.30-an lalu kembali (kasus nyata: cut @0.36 padahal prediksi benar). Saat KONFIRMASI berlawanan arah → cut-loss segera + stop entry.
- **Anti-melawan-pasar**: entry hanya jika arah sinyal searah tren harga saat ini (UP saat harga naik, DOWN saat turun), dan tidak membeli token < `TRADE_MIN_ASK` (0.35) — token semurah itu = sisi yang pasar sudah yakin kalah.
- `TRADE_DRY_RUN=true` → hanya mencetak rencana order (lookup market + token) tanpa eksekusi. Aman untuk uji coba sebelum live.

**Dana tidak pernah di-withdraw.** Semua USDC dan token hasil beli tetap sebagai collateral di dalam Polymarket (default CLOB). Untuk mengecek posisi/saldo: buka polymarket.com atau gunakan `client.list_positions(...)` dari SDK.

```
[07:57:00] PREDIKSI: UP 🟢 (Prob: 64.7%) [empirik-tegas (18 sampel)]
[07:57:01] TRADE [ORDER OK]: btc-updown-5m-1787702100 UP orderID=0xabcdef1234...
[08:00:12] VERIFY: btc-updown-5m-1787702100 BENAR ...
```

## Output Contoh

```
[07:59:45] MARKET: btc-updown-5m-1787702100 (07:55 PM-08:00 PM ET)
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

# Auto-trade Polymarket
POLY_PRIVATE_KEY=0x...            # private key penandatangan (EOA)
# POLY_FUNDER_ADDRESS TIDAK dipakai — SDK menurunkan Deposit Wallet dari private key
AUTO_TRADE=false                  # true untuk mengaktifkan order otomatis
TRADE_AMOUNT_USD=5.0              # nominal per window (USD)
TRADE_ON_URGENT=false             # true = eksekusi juga sinyal URGENT
TRADE_DRY_RUN=true                # true = cetak rencana order, tanpa eksekusi
TRADE_MAX_ASK=0.9                 # skip order jika best ask > ambang (harga masuk maksimal, jalur normal)
TRADE_HARD_MAX_ASK=0.65           # batas keras semua mode: beli hanya jika ask <= ini (hindari 0.90+ = EV negatif)
TRADE_MIN_ASK=0.35                # jangan beli token semurah ini (sisi yang pasar sudah yakin kalah)
TRADE_AGGRESSIVE=true             # prob >= TRADE_MIN_PROB -> langsung beli (lewati TRADE_MAX_ASK)
TRADE_MIN_PROB=75                 # ambang probabilitas mode agresif, dalam persen
SELL_BID_MIN=0.95                 # take-profit: jual jika best bid >= ambang
SELL_ROI_MIN=0.10                 # take-profit ROI: jual saat (bid - entry)/entry >= ini (default 10%)
SELL_CUT_LOSS=0.25                # cut-loss: jual jika best bid <= ambang (jual hanya saat benar-benar mati)
SELL_CUT_LOSS_MIN_ELAPSED=90      # jangan cut-loss di < N detik pertama sejak entry (market masih volatile)
```

> `.env` di-ignore oleh git. Jangan pernah commit isinya — mengandung secret.
> API key CLOB (`POLY_API_KEY`/`POLY_API_SECRET`/`POLY_API_PASSPHRASE`) **tidak wajib** — SDK `polymarket-client` menurunkannya otomatis dari `POLY_PRIVATE_KEY`.

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
| `Failed: api.binance.com` dkk | Normal jika jaringan memblokir domain itu. Mirror `data-api.binance.vision` sudah **diprioritaskan pertama** sejak 2026 — sukses tanpa log error. |
| `[AI] retry` di log        | Normal — model reasoning kadang timeout, bot otomatis retry sekali lalu fallback. |
| Waktu ET tidak pas         | Pastikan pakai Python 3.9+ (modul `zoneinfo` tersedia).   |

---

## Pelajaran Kunci

1. **Window delta adalah raja.** TA jangka pendek (EMA, RSI) sangat bising di skala 5 menit. Delta vs harga buka window adalah jawaban langsung atas pertanyaan market.
2. **Timing masuk itu segalanya.** PREDIKSI di T-180s (margin besar, arah belum terkunci) → KONFIRMASI di T-60s (1 menit terakhir, arah lebih terkunci). Bertindak pakai angka probabilitas empiris, bukan sekadar arah.
3. **AI hanya pelengkap.** Jangan biarkan AI membalik sinyal saat delta sudah tegas — itu justru menambah noise.
4. **Rate limit Binance itu nyata.** Bot me-retry otomatis; kalau sering gagal, kurangi frekuensi fetch.
