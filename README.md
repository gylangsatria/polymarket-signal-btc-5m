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
- Probabilitas = **estimasi Wilson** (shrinkage ke 50%): konservatif saat sampel sedikit, mendekati win rate saat sampel banyak. Contoh: `1/1 → 60%`, `7/10 → 64%`, `44/48 → 89%` — tidak ada lagi klaim ekstrem 100%/0% dari 1-2 sampel.
- Kalibrasi: bucket `|delta|` (tegas/kuat/sedang/tipis) dipakai jika ≥ 8 sampel; kalau belum cukup, **pooling semua sampel** (lebih stabil); tanpa sampel sama sekali → skor aturan.
- Probabilitas yang sama dipakai untuk **sinyal cetak DAN keputusan trade** (entry dinamis) — konsisten, tidak overconfident.
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

Saat `AUTO_TRADE=true`, bot mengeksekusi market order **FOK** (fill-or-kill) di CLOB Polymarket lewat SDK resmi `polymarket-client`:

- **Sinyal UP** → beli token **Up** (`btc-updown-5m-{window}`), **sinyal DOWN** → beli token **Down**.
- **Entry dinamis**: mulai menit ke-1 (60s) sampai menit ke-4,5 (270s), bot mengecek tiap `RECHECK_INTERVAL` detik (default 5) — masuk begitu probabilitas & harga cocok, tanpa harus menunggu PREDIKSI. Tidak perlu order parsial menggantung.
- **Guard harga adaptif (EV≥0, semua mode)**:
  - `TRADE_MIN_PROB_ENTRY` (50) — **lantai keyakinan mutlak**: prob < 50% tidak pernah masuk, jalur mana pun (model ragu = sering salah arah).
  - `TRADE_HARD_MAX_ASK` (0.85) — ceiling mutlak: tidak pernah bayar lebih dari 85¢.
  - **Guard EV**: tidak pernah bayar lebih dari keyakinan model — `ask ≤ prob%` (EV ≥ 0). Harga 0.70–0.85 boleh dibeli **hanya jika model yakin ≥ itu**; harga 0.85–0.99 dengan prob 90% = EV +5% (layak), harga 0.95 dengan prob 80% = EV −15% (ditolak).
  - `TRADE_MIN_ASK` (0.35) — jangan beli token semurah ini (sisi yang pasar sudah yakin kalah).
- **Mode agresif** (`TRADE_AGGRESSIVE=true`): jika probabilitas ≥ `TRADE_MIN_PROB` (75) → langsung FOK, **lewati** `TRADE_MAX_ASK` — tapi **tetap tunduk** lantai `TRADE_MIN_PROB_ENTRY`, ceiling `TRADE_HARD_MAX_ASK`, guard EV (`ask ≤ prob%`), & `TRADE_MIN_ASK`.
- **Anti-melawan-pasar**: entry hanya jika arah sinyal **searah tren harga saat ini** (UP saat harga naik, DOWN saat turun); kalau melawan tren, tunggu.
- **Take-profit & cut-loss**: setelah posisi terbentuk, bot cek best bid tiap `RECHECK_INTERVAL` detik (default 5).
  - ROI ≥ `SELL_ROI_MIN` (10%) → jual FOK, kunci profit, lalu **berhenti di window itu** (tunggu market berikutnya). Set `STOP_AFTER_TAKE_PROFIT=false` untuk perilaku lama: bisa beli lagi / scalping dalam 1 window.
  - bid ≤ `SELL_CUT_LOSS` (0.25) **dan** sudah ≥ `SELL_CUT_LOSS_MIN_ELAPSED` (90s) sejak entry → jual FOK, ambil sisa nilai, lalu **berhenti entry di window itu** (1 rugi per window cukup).
  - Jeda 90s = window 5m volatil di menit 1-2; tanpa jeda bot sempat cut @0.36 padahal prediksi benar (harga sempat menyapu rendah lalu kembali).
  - KONFIRMASI berlawanan arah dengan posisi → cut-loss **segera** (tanpa jeda) + stop entry.
- **Maksimal 1 posisi terbuka**, dan default **1 trade per window** (profit atau rugi) — sisanya tunggu market berikutnya.
- `TRADE_ON_URGENT=true` → sinyal URGENT (delta ≥ 0.15% di awal) juga dieksekusi; `TRADE_DRY_RUN=true` → cetak rencana order tanpa eksekusi (uji coba aman).

**Dana tidak pernah di-withdraw.** Semua USDC dan token hasil beli tetap sebagai collateral di dalam Polymarket (default CLOB). Untuk mengecek posisi/saldo: buka polymarket.com atau gunakan `client.list_positions(...)` dari SDK.

```
[07:57:00] PREDIKSI: UP 🟢 (Prob: 64.7%) [empirik-tegas (18 sampel)]
[07:57:01] TRADE [ORDER OK]: btc-updown-5m-1787702100 UP orderID=0xabcdef1234...
[08:00:12] VERIFY: btc-updown-5m-1787702100 BENAR ...
```

## Output Contoh

```
[07:59:45] MARKET: btc-updown-5m-1787702100 (07:55 PM-08:00 PM ET)
[07:59:45] PREDIKSI: UP 🟢 (Prob: 75.0%) [aturan]
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
AUTO_TRADE=false                  # false = signal-only; true = auto-trading
TRADE_AMOUNT_USD=1.0              # nominal per window (USD)
TRADE_ON_URGENT=false             # true = eksekusi juga sinyal URGENT
TRADE_DRY_RUN=true                # true = cetak rencana order, tanpa eksekusi
TRADE_MAX_ASK=0.6                 # jalur normal: skip jika best ask > ambang
TRADE_HARD_MAX_ASK=0.85           # ceiling mutlak: tidak pernah bayar > 85ct (guard EV menyaring harga >= prob%)
TRADE_MIN_ASK=0.35                # jangan beli token semurah ini (sisi yang pasar sudah yakin kalah)
TRADE_AGGRESSIVE=true             # prob >= TRADE_MIN_PROB -> langsung beli (lewati TRADE_MAX_ASK)
TRADE_MIN_PROB=75                 # ambang probabilitas mode agresif, dalam persen
TRADE_MIN_PROB_ENTRY=50           # lantai keyakinan MUTLAK semua mode: jangan entry jika prob < ini
RECHECK_INTERVAL=5                # detik: interval cek ulang harga & posisi (entry/TP/cut-loss); lebih kecil = lebih responsif, tapi lebih banyak hit ke Binance/CLOB
SELL_BID_MIN=0.95                 # take-profit: jual jika best bid >= ambang
SELL_ROI_MIN=0.10                 # take-profit ROI: jual saat (bid - entry)/entry >= ini (10%)
SELL_CUT_LOSS=0.25                # cut-loss: jual jika best bid <= ambang (jual hanya saat benar-benar mati)
SELL_CUT_LOSS_MIN_ELAPSED=90      # jangan cut-loss di < N detik pertama sejak entry (market masih volatile)
STOP_AFTER_TAKE_PROFIT=true       # true = setelah TP berhenti di window itu; false = bisa beli lagi (scalping)
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

## Pengaturan Interaktif (config.py)

Semua pengaturan bot hidup di **`.env`**. Ada menu interaktif untuk mengubahnya tanpa edit manual:

```bash
python3 config.py
```

1. Pilih nomor parameter (mode, nominal, interval cek, guard harga, TP/cut-loss, dll).
2. Masukkan nilai baru — tervalidasi (rentang & tipe).
3. Pilih `0` untuk simpan ke `.env` → tanya restart container → otomatis `docker compose up -d`.

Contoh:

```
 5. TRADE_HARD_MAX_ASK = 0.70   Batas keras SEMUA mode: beli hanya jika ask <= ini
   Pilih nomor: 5
   nilai baru untuk TRADE_HARD_MAX_ASK [0.70] (rentang 0.1-0.95): 0.72
   -> TRADE_HARD_MAX_ASK = 0.72
```

Alternatif manual: edit `.env` → `docker compose up -d` (nilai apa pun yang tidak ada di menu tetap bisa diatur langsung di file).

---

## Troubleshooting

| Gejala                     | Solusi                                                    |
| -------------------------- | --------------------------------------------------------- |
| `Failed: api.binance.com` dkk | Normal jika jaringan memblokir domain itu. Mirror `data-api.binance.vision` sudah **diprioritaskan pertama** sejak 2026 — sukses tanpa log error. |
| `[AI] retry` di log        | Normal — model reasoning kadang timeout, bot otomatis retry sekali lalu fallback. |
| `TRADE [SKIP] ... harga terlalu mahal — EV negatif` | Best ask > `TRADE_HARD_MAX_ASK` (0.85) — ceiling mutlak. Di bawahnya, `ask > prob%` juga ditolak guard EV. Kalau sering SKIP: model tidak yakin (prob rendah), bukan batasnya. |
| `TRADE [SKIP] ... not enough balance / allowance` | Saldo deposit wallet Polymarket < `TRADE_AMOUNT_USD`. Top-up USDC di polymarket.com atau turunkan nominal di `.env`. |
| `SKIP entry ... lawan arah` | Prediksi melawan tren harga saat ini — bot menunggu sampai searah. |
| `[AUTO_TRADE, ...]` di log vs `[signal-only]` | Mode ditentukan `AUTO_TRADE` di `.env` (true/false). |
| Waktu ET tidak pas         | Pastikan pakai Python 3.9+ (modul `zoneinfo` tersedia).   |

---

## FAQ

### 1. Kenapa bot jarang trade / sering `TRADE [SKIP]`?
Guard EV bekerja. Log `ask 0.82 > prob 25% (EV negatif)` berarti harga 82¢ tapi keyakinan model cuma 25% — bayar 0.82 untuk menang cuma +18% tapi kalah −100% = rugi terjamin. Bot hanya masuk jika **prob ≥ `TRADE_MIN_PROB_ENTRY` (50)**, `ask ≤ prob%` (EV ≥ 0) dan `ask ≤ 0.85`. Harga 0.8–0.9 **boleh** dibeli saat model yakin (prob 85–90%) — itu justru EV positif. Lebih jarang trade tapi tiap trade punya peluang untung — disengaja.

### 2. Kenapa `TRADE [SKIP]: ask 0.62 > prob 50% (EV negatif)`?
Guard EV jalur normal: harga 0.62 lebih mahal dari keyakinan model (50%) — membeli itu rugi terjamin secara statistik. Skip benar.

### 3. Kenapa kadang cut-loss padahal prediksinya benar?
Window 5m sangat volatil di 1-2 menit pertama — harga bisa menyapu 0.30-an lalu kembali (kasus nyata: cut @0.36 padahal window berakhir BENAR). Dua lapis proteksi sudah dipasang: `SELL_CUT_LOSS` diturunkan ke 0.25 (jual hanya saat benar-benar mati) dan `SELL_CUT_LOSS_MIN_ELAPSED=90` (90 detik pertama sejak entry bot HOLD). Cut-loss yang tersisa (setelah 90s, bid ≤ 0.25, atau KONFIRMASI membalik) itu memang keputusan benar.

### 4. Kenapa `not enough balance: balance 1812095, order amount 2060190`?
Saldo deposit wallet Polymarket (< $1.81) lebih kecil dari nominal order ($2.06). Top-up USDC di polymarket.com, atau turunkan `TRADE_AMOUNT_USD` di `.env`. Angka memakai unit 1e-6: `1812095` = $1.812.

### 5. Bagaimana pindah antara signal-only dan auto-trading?
Ubah `AUTO_TRADE` di `.env` → `docker compose up -d` (tanpa rebuild):
- `false` = SIGNAL-ONLY (prediksi saja, tidak ada order)
- `true` = AUTO-TRADING ($`TRADE_AMOUNT_USD` per window)
Log judul menunjukkan mode: `[AUTO-TRADE, $1.00/window]` vs `[signal-only]`.

### 6. Kenapa bot berhenti trade setelah 1 profit atau 1 rugi?
`STOP_AFTER_TAKE_PROFIT=true` (default) dan `stopped` setelah cut-loss — **1 trade per window** disengaja: kunci satu profit bersih (atau batasi satu rugi) lalu tunggu market 5 menit berikutnya. Set `STOP_AFTER_TAKE_PROFIT=false` kalau ingin scalping ulang dalam 1 window.

### 7. Apakah dana bisa ditarik ke wallet eksternal?
Tidak pernah. Semua USDC & token tetap sebagai **collateral di Polymarket** (default CLOB). Untuk cek posisi/saldo buka polymarket.com atau `client.list_positions(...)`.

### 8. Kenapa ada `SKIP entry ... lawan arah — tunggu tren`?
Bot menolak masuk saat prediksi melawan tren harga saat ini (contoh: prediksi UP tapi harga sedang turun). Anti-whipsaw — menunggu sampai sinyal & tren searah.

### 9. Bagaimana memastikan container memakai kode terbaru (stale image)?
Bug lama: `docker compose up -d --build` bisa selesai membangun image tapi container lama tetap jalan (terkill timeout). Periksa:
```bash
docker inspect $(docker ps -q -f name=polymarketbot-signal) --format '{{.Image}}'
docker images polymarket-signal --format '{{.ID}}'
```
Kalau beda: `docker compose down && docker compose up -d`.

### 10. Apa itu FOK (fill-or-kill)?
Market order yang hanya eksekusi jika seluruh nominal terisi saat itu juga; kalau tidak, dibatalkan — tidak ada posisi parsial yang menggantung. Sisa modal kembali ke deposit wallet.

---

## Pelajaran Kunci

1. **Window delta adalah raja.** TA jangka pendek (EMA, RSI) sangat bising di skala 5 menit. Delta vs harga buka window adalah jawaban langsung atas pertanyaan market.
2. **Timing masuk itu segalanya.** PREDIKSI di T-180s (margin besar, arah belum terkunci) → KONFIRMASI di T-60s (1 menit terakhir, arah lebih terkunci). Bertindak pakai angka probabilitas empiris, bukan sekadar arah.
3. **AI hanya pelengkap.** Jangan biarkan AI membalik sinyal saat delta sudah tegas — itu justru menambah noise.
4. **Rate limit Binance itu nyata.** Bot me-retry otomatis; kalau sering gagal, kurangi frekuensi fetch.
