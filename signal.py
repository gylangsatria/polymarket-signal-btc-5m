import os
import time
import json
import requests
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

import trader  # auto-trade (lazy import polymarket-client di dalamnya)

load_dotenv()

ET = ZoneInfo("America/New_York")  # auto-detect EDT/EST (DST)

# data-api.binance.vision = mirror publik — satu-satunya yang terjangkau dari jaringan
# server ini (api.binance.com dkk dapat "No route to host"/Errno 113). Taruh paling depan.
BINANCE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
]

# --- AI (endpoint kompatibel OpenAI) ---
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini").strip()

SPARK = "▁▂▃▄▅▆▇█"

# Sinyal URGENT jika delta sangat kuat di awal window.
TRIGGER_URGENT_MIN_DELTA = 0.15
TRIGGER_FIRST_SEC = 120   # T-180s
TRIGGER_CONFIRM_SEC = 240 # T-60s (1 menit sebelum tutup)
RECHECK_INTERVAL = 15     # recheck probabilitas (untuk trigger beli) per N detik
# Anti-whipsaw: KONFIRMASI hanya membalik arah jika delta berlawanan lebih dari ini (%).
# Pembalikan kecil (harga nyaris di open) sering noise — tahan arah PREDIKSI (HOLD).
FLIP_MIN_DELTA = 0.03
MAX_RULE_CONF = 80.0      # confidence aturan dibatasi — 100% terlalu yakin untuk prediksi 1 menit.
STATS_FILE = "stats.json"  # riwayat prediksi vs hasil aktual (win rate empiris)


def bucket(delta_abs):
    """Kelompok |delta| untuk kalibrasi probabilitas empiris."""
    if delta_abs >= 0.10: return "tegas"
    if delta_abs >= 0.02: return "kuat"
    if delta_abs >= 0.005: return "sedang"
    return "tipis"


def load_stats():
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_stats(stats):
    try:
        with open(STATS_FILE, "w") as f:
            # default: tangani sisa nilai numpy (bool_/float64) jika lolos dari konversi eksplisit
            json.dump(stats, f, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    except Exception as e:
        print(f"[stats] gagal simpan: {e}")


def sparkline(values):
    """Grafik harga ASCII (zero-dependency)."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    rng = hi - lo or 1e-9
    return "".join(SPARK[min(7, int((v - lo) / rng * 8))] for v in values)

def fetch_price(symbol="BTCUSDT", limit=200):
    for url in BINANCE_URLS:
        try:
            params = {"symbol": symbol, "interval": "1m", "limit": limit}
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            df = pd.DataFrame(r.json(), columns=[
                "ts", "open", "high", "low", "close", "vol",
                "close_ts", "quote_av", "trades", "tb_base_av", "tb_quote_av", "ignore"
            ])
            df[["open","high","low","close","vol"]] = df[["open","high","low","close","vol"]].astype(float)
            return df
        except Exception as e:
            print(f"Failed: {url} ({e})")
            continue
    return None


def ask_ai(delta_pct, cur_price, closes):
    """Tiebreaker AI untuk sinyal ambigu. Return (direction, confidence) atau None."""
    # Prompt ringkas: model reasoning (deepseek-v4-flash) suka menghabiskan semua
    # token kalau diberikan 40 angka mentah. Kirim ringkasan + 12 close terakhir.
    recent = ", ".join(f"{c:.2f}" for c in closes[-12:])
    chg_1m = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0
    chg_5m = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 5 else 0
    chg_15m = (closes[-1] - closes[-16]) / closes[-16] * 100 if len(closes) > 15 else 0
    prompt = (
        f"BTC 5-min binary market. Window open {cur_price / (1 + delta_pct / 100):.2f}, "
        f"current {cur_price:.2f} ({delta_pct:+.3f}% vs open). "
        f"1m {chg_1m:+.3f}%, 5m {chg_5m:+.3f}%, 15m {chg_15m:+.3f}%. "
        f"Last 12 closes: [{recent}]. "
        f"Will the close be UP or DOWN vs the window open? "
        f'Reply ONLY compact JSON: {{"direction":"UP"|"DOWN","confidence":0-100}}'
    )
    try:
        r = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}"},
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a precise crypto short-term analyst. Answer only with compact JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 512,
                "reasoning_effort": "low",
            },
            timeout=12,
        )
        r.raise_for_status()
        # Gateway kadang menambahkan 'data: [DONE]' setelah JSON; potong di antara { ... }.
        text = r.text.strip()
        body = json.loads(text[text.find("{"): text.rfind("}") + 1])
        msg = body["choices"][0]["message"]
        # Model reasoning (deepseek-r1) kadang menaruh jawaban di reasoning_content saat token habis.
        content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        # Cari JSON object pertama di output (model kadang nambah teks tambahan).
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(content[start:end + 1])
        else:
            raise json.JSONDecodeError("no json object", content, 0)
        d = str(data.get("direction", "")).upper()
        c = float(data.get("confidence", 50))
        if d in ("UP", "DOWN"):
            return ("UP 🟢" if d == "UP" else "DOWN 🔴"), max(0.0, min(100.0, c))
    except Exception as e:
        print(f"[AI] retry ({type(e).__name__}: {str(e)[:80]})")
    # Retry sekali: model reasoning kadang habis token di reasoning_content, content kosong.
    try:
        r = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}"},
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "Reply with ONLY valid JSON. No thinking, no explanation."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 150,
                "reasoning_effort": "low",
            },
            timeout=12,
        )
        r.raise_for_status()
        text = r.text.strip()
        body = json.loads(text[text.find("{"): text.rfind("}") + 1])
        content = (body["choices"][0]["message"].get("content") or "").strip()
        data = json.loads(content[content.find("{"): content.rfind("}") + 1])
        d = str(data.get("direction", "")).upper()
        c = float(data.get("confidence", 50))
        if d in ("UP", "DOWN"):
            return ("UP 🟢" if d == "UP" else "DOWN 🔴"), max(0.0, min(100.0, c))
    except Exception as e:
        print(f"[AI] skipped ({type(e).__name__}: {str(e)[:80]})")
    return None


def get_signal(allow_ai=True):
    now = int(time.time())
    window_ts = now - (now % 300)
    
    df = fetch_price()
    if df is None or df.empty:
        return None, 0, 0, 0, False, [], 0.0
    
    window_row = df[df["ts"] == window_ts * 1000]
    if window_row.empty:
        window_row = df[df["ts"] < window_ts * 1000].iloc[-1:]
    
    open_price = window_row["open"].iloc[0]
    cur_price = df["close"].iloc[-1]
    delta = (cur_price - open_price) / open_price * 100

    score = 0
    if abs(delta) > 0.10: score += 7 if delta > 0 else -7
    elif abs(delta) > 0.02: score += 5 if delta > 0 else -5
    elif abs(delta) > 0.005: score += 3 if delta > 0 else -3
    elif abs(delta) > 0.001: score += 1 if delta > 0 else -1

    ema9 = df["close"].ewm(span=9).mean().iloc[-1]
    if cur_price > ema9: score += 1
    else: score -= 1

    direction = "UP" if score > 0 else "DOWN"
    confidence = min(MAX_RULE_CONF, abs(score) / 8 * 100)

    # ponytail: AI hanya jadi tiebreaker saat sinyal aturan lemah (|score|<=4);
    # delta jendela tetap dominan. Kalau mau AI selalu konsultasi, hapus syarat abs(score).
    ai_used = False
    if allow_ai and AI_API_KEY and abs(score) <= 4:
        ai = ask_ai(delta, cur_price, df["close"].tolist())
        if ai:
            direction = ai[0].split()[0]  # "UP 🟢" -> "UP"
            confidence = max(confidence, min(ai[1], 70))
            ai_used = True

    return direction, confidence, open_price, cur_price, ai_used, df["close"].tolist(), delta

def emit_signal(current_window, stats, tag, prev_up=None):
    """Cetak sinyal + probabilitas. Return (window, up, |delta|, prob) atau None.

    prev_up = arah PREDIKSI. Anti-whipsaw: jika arah baru berlawanan tapi
    |delta|-nya kecil (< FLIP_MIN_DELTA), arah ditahan (HOLD) — pembalikan
    tipis mendekati harga open sering noise dan bisa balik lagi.
    """
    direction, confidence, op, cp, ai_used, closes, delta = get_signal()
    if not direction:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Signal failed (Binance error).")
        return None
    up = direction == "UP"
    held = False
    if prev_up is not None and up != prev_up and abs(delta) < FLIP_MIN_DELTA:
        up, held = prev_up, True
        direction = "UP" if up else "DOWN"
        confidence = min(confidence, 40.0)
    dir_txt = "UP 🟢" if up else "DOWN 🔴"
    et_start = datetime.fromtimestamp(current_window, tz=ET)
    et_end = datetime.fromtimestamp(current_window + 300, tz=ET)
    et_str = f"{et_start.strftime('%I:%M %p')}-{et_end.strftime('%I:%M %p')} ET"
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] MARKET: {trader.SLUG_PREFIX}-{current_window} ({et_str})")
    # Probabilitas = win rate empiris bucket delta (>=15 sampel), else skor aturan
    d_abs = abs(delta)
    b = bucket(d_abs)
    rows = [s for s in stats if s["bucket"] == b]
    if len(rows) >= 15:
        prob = sum(s["win"] for s in rows) / len(rows) * 100
        src = f"empirik-{b} ({len(rows)} sampel)"
    else:
        prob = confidence
        src = "aturan"
    hold_txt = " [HOLD]" if held else ""
    print(f"[{ts}] {tag}: {dir_txt} (Prob: {prob:.1f}%){' [AI]' if ai_used else ''}{hold_txt} [{src}]")
    print(f"[{ts}] Prices: Open {op:.2f} -> Cur {cp:.2f} (delta {delta:+.3f}%)")
    print(f"[{ts}] Chart  : {sparkline(closes[-40:])}")
    print("-" * 50)
    return (current_window, up, d_abs, prob)


def do_trade(current_window, up, prob=None):
    """Eksekusi auto-trade via trader.py. Return True jika order sukses."""
    global position
    ts = datetime.now().strftime("%H:%M:%S")
    res = trader.trade(current_window, up, prob=prob)
    if res.get("ok"):
        tag = "DRY-RUN" if res.get("msg") == "DRY-RUN" else "ORDER OK"
        extra = res.get("order_id", "")
        print(f"[{ts}] TRADE [{tag}]: {trader.SLUG_PREFIX}-{current_window} {'UP' if up else 'DOWN'}"
              + (f" orderID={extra[:18]}" if extra else ""))
        # Simpan posisi untuk take-profit/cut-loss (hanya order nyata — DRY-RUN tanpa shares)
        if res.get("token_id") and res.get("shares"):
            position = (current_window, "UP" if up else "DOWN", res["token_id"], res["shares"])
        return True
    else:
        print(f"[{ts}] TRADE [SKIP]: {trader.SLUG_PREFIX}-{current_window} ({res.get('msg')})")
    return res.get("ok", False)


def do_sell(window_ts, token_id, shares, reason="TAKE-PROFIT"):
    """Jual posisi (FOK). Return True jika terisi."""
    ts = datetime.now().strftime("%H:%M:%S")
    res = trader.sell(token_id, shares)
    if res.get("ok"):
        print(f"[{ts}] SELL [{reason}]: {trader.SLUG_PREFIX}-{window_ts} token={token_id[:12]} "
              f"received=${res.get('received')}")
        return True
    print(f"[{ts}] SELL [{reason} SKIP]: {trader.SLUG_PREFIX}-{window_ts} ({res.get('msg')})")
    return False


# Modul-level: posisi yang sedang dipegang (window_ts, arah, token_id, shares).
# Dipakai bersama do_trade (tulis) dan main (kelola take-profit/cut-loss).
position = None


def main():
    global position
    mode = "AUTO-TRADE" if trader.enabled() else "signal-only"
    dry = " (DRY-RUN)" if trader.DRY_RUN else ""
    amt = f", ${trader.AMOUNT_USD:.2f}/window" if trader.enabled() else ""
    print(f"Polymarket Signal Bot [{mode}{dry}{amt}] - Monitoring...")
    print("-----------------------------------------------------")

    last_window = -1
    pending = None  # (window_ts, prediksi_up, |delta| saat sinyal) — dari sinyal TERAKHIR
    stats = load_stats()
    if stats:
        wins = sum(s["win"] for s in stats)
        print(f"Riwayat: {len(stats)} prediksi, win rate {wins/len(stats)*100:.1f}%")

    while True:
        try:
            now = int(time.time())
            current_window = now - (now % 300)
            time_into_window = now % 300

            # Window baru → reset penanda sinyal
            if current_window != last_window:
                last_window = current_window
                urgent_done = first_done = second_done = False
                traded = False  # maksimal 1 order per window
                window_up = None  # arah PREDIKSI window ini (acuan anti-whipsaw)
                last_recheck = 0.0
                position = None  # window baru — posisi lama selesai (jual/hangus/redeem)

            # Verifikasi hasil window sebelumnya (kline final siap ~10s setelah tutup)
            if pending and current_window != pending[0] and time_into_window >= 10:
                # ... (kode verifikasi tetap sama) ...
                w, up, d_abs, _ = pending
                df = fetch_price(limit=20)
                if df is not None and not df.empty:
                    o = df[df["ts"] == w * 1000]
                    c = df[df["ts"] == (w + 240) * 1000]
                    if not o.empty and not c.empty:
                        open_p = o["open"].iloc[0]
                        final_p = c["close"].iloc[0]
                        win = bool(up == (final_p > open_p))
                        stats.append({"window": int(w), "up": bool(up), "win": win, "delta": float(d_abs), "bucket": bucket(d_abs)})
                        save_stats(stats)
                        total = len(stats)
                        wins = sum(s["win"] for s in stats)
                        ts = datetime.now().strftime("%H:%M:%S")
                        mark = "BENAR" if win else "SALAH"
                        print(f"[{ts}] VERIFY: {trader.SLUG_PREFIX}-{w} {mark} (close {final_p:.2f} vs open {open_p:.2f}) | win rate {wins/total*100:.1f}% ({wins}/{total})")
                        pending = None

            # Sinyal URGENT (60s - 120s) - Hanya jika delta sangat kuat (>= 0.15%)
            if 60 <= time_into_window < TRIGGER_FIRST_SEC and not urgent_done:
                _, _, op, cp, _, _, _ = get_signal()
                delta = (cp - op) / op * 100
                if abs(delta) >= TRIGGER_URGENT_MIN_DELTA:
                    p = emit_signal(current_window, stats, "URGENT")
                    if p:
                        pending = p
                        window_up = p[1]
                        # Entry cepat hanya jika diaktifkan (TRADE_ON_URGENT=true)
                        if trader.enabled() and trader.trade_on_urgent() and not traded:
                            traded = do_trade(current_window, p[1], p[3])
                    urgent_done = True

            # Sinyal awal di menit ke-2 (T-180s)
            if time_into_window >= TRIGGER_FIRST_SEC and not first_done:
                # Jika sudah urgent, tidak perlu cetak prediksi dasar kecuali arah berubah (jarang)
                p = emit_signal(current_window, stats, "PREDIKSI")
                if p:
                    pending = p
                    window_up = p[1]
                    # Eksekusi di menit ke-2 (harga masih wajar); skip otomatis jika ask > ambang.
                    # KONFIRMASI T-60s di bawah jadi fallback bila belum ada order.
                    if trader.enabled() and not traded:
                        traded = do_trade(current_window, p[1], p[3])
                first_done = True

            # Recheck tiap 15 detik: jika belum trade & probabilitas naik >= ambang
            # agresif, langsung eksekusi — tidak menunggu KONFIRMASI.
            if (first_done and not traded and not second_done
                    and time.time() - last_recheck >= RECHECK_INTERVAL):
                last_recheck = time.time()
                direction, confidence, _, _, _, _, delta = get_signal(allow_ai=False)
                if direction:
                    d_abs = abs(delta)
                    b = bucket(d_abs)
                    rows = [s for s in stats if s["bucket"] == b]
                    prob = (sum(s["win"] for s in rows) / len(rows) * 100
                            if len(rows) >= 15 else confidence)
                    if prob >= trader.MIN_PROB:
                        up = direction == "UP"
                        ts = datetime.now().strftime("%H:%M:%S")
                        print(f"[{ts}] RECHECK: {'UP' if up else 'DOWN'} prob {prob:.1f}% >= {trader.MIN_PROB:.0f}% — eksekusi")
                        traded = do_trade(current_window, up, prob)

            # Kelola posisi tiap recheck: TAKE-PROFIT jika bid >= SELL_BID_MIN,
            # CUT-LOSS jika bid <= SELL_CUT_LOSS (sisa nilai — jual daripada hangus 0).
            if position and time.time() - last_recheck >= RECHECK_INTERVAL:
                last_recheck = time.time()
                w, direction, token_id, shares = position
                bid = trader.get_best_bid(token_id)
                ts = datetime.now().strftime("%H:%M:%S")
                if bid is None:
                    pass  # tidak ada pembeli — tunggu recheck berikutnya
                elif bid >= trader.SELL_BID_MIN:
                    print(f"[{ts}] TARGET: bid {bid:.2f} >= {trader.SELL_BID_MIN:.2f} — TAKE-PROFIT")
                    if do_sell(w, token_id, shares, reason="TAKE-PROFIT"):
                        position = None
                elif bid <= trader.SELL_CUT_LOSS:
                    print(f"[{ts}] TARGET: bid {bid:.2f} <= {trader.SELL_CUT_LOSS:.2f} — CUT-LOSS")
                    if do_sell(w, token_id, shares, reason="CUT-LOSS"):
                        position = None

            # Konfirmasi T-60s sebelum tutup (1 menit terakhir; menimpa pending — keputusan final)
            if time_into_window >= TRIGGER_CONFIRM_SEC and not second_done:
                p = emit_signal(current_window, stats, "KONFIRMASI", prev_up=window_up)
                if p:
                    pending = p
                    # Eksekusi auto-trade: sekali per window, arah KONFIRMASI (final)
                    if trader.enabled() and not traded:
                        traded = do_trade(current_window, p[1], p[3])
                    # Arah berbalik vs posisi yang sudah dipegang → cut-loss sebelum hangus total
                    if position:
                        pos_dir = position[1]
                        conf_dir = "UP" if p[1] else "DOWN"
                        if pos_dir != conf_dir:
                            w, _dir, token_id, shares = position
                            ts = datetime.now().strftime("%H:%M:%S")
                            print(f"[{ts}] KONFIRMASI {conf_dir} berlawanan posisi {pos_dir} — CUT-LOSS")
                            if do_sell(w, token_id, shares, reason="CUT-LOSS"):
                                position = None
                second_done = True

            time.sleep(1)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
