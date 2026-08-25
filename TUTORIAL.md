# Tutorial Lengkap: Polymarket BTC 5-Minute Trading Bot di Docker

Tutorial ini membimbing Anda untuk meng‑setup, menjalankan, dan mengoptimalkan bot trading Polymarket BTC 5‑minute Up/Down yang berjalan di Docker. Ikuti langkah demi langkah agar bot berjalan dengan akurat.

---

## 1. Persiapan Lingkungan

### 1.1 Pastikan Docker Terpasang

Docker Desktop (Windows/macOS) atau Docker Engine (Linux) harus sudah terpasang dan berjalan.

```bash
docker --version
docker compose version
```

Anda harus melihat versi Docker dan Docker Compose yang terpasang.

---

## 2. Kloning Repositori

Unduh / kloning repositori bot ini ke komputer Anda:

```bash
git clone https://github.com/username/PolymarketBot.git
cd PolymarketBot
```

---

## 3. Konfigurasi Akun Polymarket

### 3.1 Akun & Private Key

- Punya akun Polymarket di https://polymarket.com.
- Akun harus memiliki USDC di jaringan **Polygon**.
- Export **private key** dompet Polymarket Anda. Caranya:
  1. Login ke Polymarket.
  2. Buka **Settings > Wallet > Export Private Key**.
  3. Salin kunci pribadi (format `0x...`).

### 3.2 Derive API Credentials

Jalankan skrip `setup_creds.py` untuk menghasilkan API credentials dari private key:

> **Catatan:** Jalankan ini **sekali saja**. Credentials yang dihasilkan cukup permanen.

Cara 1 — secara lokal (opsional):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 setup_creds.py
```

Skrip akan mencetak output seperti:

```
--- NEW API CREDENTIALS ---
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...
POLY_FUNDER_ADDRESS=0x...
```

Salin semua nilai ini. Jika Anda tidak dapat menjalankan secara lokal, jalankan lewat Docker (lihat langkah 4.2).

---

## 4. Konfigurasi .env

Buat file `.env` dari contoh:

```bash
cp .env.example .env
```

Buka `.env` dan isi semua nilai:

```env
# Polymarket credentials
POLY_PRIVATE_KEY=0x...your_private_key...
POLY_API_KEY=...derived...
POLY_API_SECRET=...derived...
POLY_API_PASSPHRASE=...derived...
POLY_FUNDER_ADDRESS=0x...your_proxy_wallet...
POLY_SIGNATURE_TYPE=1

# Auto-claimer (optional)

### 5.2 Jalankan Bot

```bash
docker compose up -d bot
```

Bot akan otomatis berjalan di latar belakang. Untuk melihat log:

```bash
docker compose logs -f bot
```

Tekan `Ctrl + C` untuk berhenti melihat log (bot tetap berjalan).

---

## 6. Mode Operasi Bot

Anda bisa mengganti `BOT_MODE` di `.env` sebelum build / restart. Empat mode berikut didukung:

| Mode          | Strategi                                    | Confidence Minimum | Risiko              |
| ------------- | ------------------------------------------- | ------------------ | ------------------- |
| `flat`        | Taruh 25 % bankroll tiap trade.             | 0 %                | Stabil, rendah ROI. |
| `safe`        | Sama seperti flat, tapi butuh confidence 30 %. | 30 %             | Konservatif.       |
| `aggressive`  | Taruh profit di atas investasi awal.        | 20 %               | Medium.             |
| `degen`       | All‑in setiap trade.                        | 0 %                | Sangat tinggi.      |

Setelah mengganti mode, restart service:

```bash
docker compose stop bot
docker compose up -d bot
```

---

## 7. Dry Run (Uji Coba Tanpa Risiko)

Untuk menguji bot dengan **data riil** tetapi **tanpa melakukan trade sungguhan**, ubah `docker-compose.yml`:

```yaml
command: python3 bot.py --dry-run
```

Atau jalankan langsung di dalam container:

```bash
docker compose exec bot python3 bot.py --dry-run --mode safe
```

---

## 8. Auto Claimer (Klaim Otomatis Kemenangan)

Jika Anda ingin bot otomatis mengklaim token yang menang:

```bash
docker compose up -d auto-claimer
```

> Pastikan `POLY_EMAIL` dan `POLY_PASSWORD` di `.env` sudah diisi. Jika belum, layanan ini akan melewati klaim.

---

## 9. Monitoring & Debug

### Lihat Log Real-Time

```bash
docker compose logs -f --tail=100
```

### Lihat Status Container

```bash
docker compose ps
```

### Restart Bot

```bash
docker compose restart bot
```

### Hentikan Semua Layanan

```bash
docker compose down
```

---

## 10. Pemecahan Masalah Umum

| Error                                  | Solusi                                                  |
| -------------------------------------- | ------------------------------------------------------- |
| `Error fetching market info`           | Market belum dibuka. Bot akan retry otomatis.           |
| `Binance rate limit`                   | Bot retry otomatis. Tidak perlu tindakan manual.        |
| `Login failed` (auto_claim)            | Cek `POLY_EMAIL` / `POLY_PASSWORD` / 2FA.               |
| `.env tidak ditemukan`                 | Salin `.env.example` → `.env` dan isi.                  |
| `Insufficient USDC`                    | Isi USDC ke dompet Anda.                                |

---

## 11. Tips & Best Practices

1. **Gunakan `--dry-run` dulu.** Uji strategi dengan data riil selama 1–2 sesi sebelum trade sungguhan.

2. **Mulai dari mode `safe`.** Sebaiknya tidak beralih ke `degen` atau `aggressive` sebelum memahami performa bot.

3. **Monitor log secara rutin.** Jika terlihat banyak error Binance / rate limit, pertimbangkan mengurangi frekuensi request.

4. **Jaga minimal bankroll.** Pastikan `STARTING_BANKROLL >= MIN_BET * 5` agar bot tidak terjebak saat drawdown.

5. **Gunakan `.dockerignore`.** File ini sudah ada untuk mencegah `.env` / `venv` masuk image, jaga keamanan kredensial.

POLY_EMAIL=your_email@example.com
POLY_PASSWORD=your_password

# Bot settings
STARTING_BANKROLL=1.0
MIN_BET=1.0
BOT_MODE=safe
```

### Penjelasan Setiap Variabel

| Variabel                   | Keterangan                                                |
| -------------------------- | --------------------------------------------------------- |
| `POLY_PRIVATE_KEY`         | Private key dompet Polymarket (wajib).                    |
| `POLY_API_KEY`             | API Key yang sudah diderive.                              |
| `POLY_API_SECRET`          | API Secret yang sudah diderive.                           |
| `POLY_API_PASSPHRASE`      | API Passphrase yang sudah diderive.                       |
| `POLY_FUNDER_ADDRESS`      | Alamat dompet Anda.                                       |
| `POLY_SIGNATURE_TYPE`      | `1` (POLY_PROXY / signature type default).                |
| `POLY_EMAIL` / `POLY_PASSWORD` | Email & password akun (untuk auto_claim.py). Jika tidak pakai auto-claimer, kosongkan / hapus. |
| `STARTING_BANKROLL`        | Bankroll awal USDC.                                       |
| `MIN_BET`                  | Minimum taruhan per trade (USDC).                         |
| `BOT_MODE`                 | Mode bot: `flat`, `safe`, `aggressive`, atau `degen`.     |

---

## 5. Build & Jalankan di Docker

### 5.1 Build Image

```bash
docker compose build
```

Proses ini akan:
- Meng‑install semua dependensi Python (`py-clob-client`, `pandas`, `playwright`, dll).
- Meng‑install browser Chromium untuk `auto_claim.py`.

Butuh waktu 2–5 menit tergantung jaringan.
