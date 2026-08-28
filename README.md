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

Total skor > 0 → **UP ������**, < 0 → **DOWN ������**. Confidence = `|skor|/8 × 100%`, **dibatasi maks 80%** — prediksi 1 menit tidak pernah layak klaim 100%.

**Anti-whipsaw (HOLD):** jika KONFIRMASI (T-60s) berubah arah tapi `|delta| < 0.03%` (harga nyaris di open), arah **ditahan** mengikuti PREDIKSI dan confidence dibatasi 40%. Pembalikan tipis sering noise yang bisa balik lagi; flip hanya jika delta berlawanan **tegas** (≥ 0.03%).

---

## Akurasi & Verifikasi

- Setelah window tutup, bot **memverifikasi** prediksi vs harga close aktual (`VERIFY: ... BENAR/SALAH`) dan menyimpan riwayat di `stats.json`.
- Probabilitas = **estimasi Wilson** (shrinkage ke 50%): konservatif saat sampel sedikit, mendekati win rate saat sampel banyak. Contoh: `1/1 → 60%`, `7/10 → 64%`, `44/48 → 89%` — tidak ada lagi klaim ekstrem 100%/0% dari 1-2 sampel.
- Kalibrasi: bucket `|delta|` (tegas/kuat/sedang/tipis) dipakai jika ≥ 8 sampel; kalau belum cukup, **pooling semua sampel** (lebih stabil); tanpa sampel sama sekali → skor aturan.
- Probabilitas yang sama dipakai untuk **sinyal cetak DAN keputusan trade** (entry dinamis) — konsisten, tidak overconfident.
- `[HOLD]` di KONFIRMASI = arah PREDIKSI dipertahankan karena pembalikan tipis (< 0.03%) dianggap noise.
- Mulai fresh: hapus `stats.json`. Riwayat menumpuk antar-restart.