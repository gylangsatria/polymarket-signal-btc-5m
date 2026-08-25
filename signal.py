import os
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BINANCE_URLS = [
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",  # public mirror
]

# --- AI (endpoint kompatibel OpenAI) ---
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini").strip()

SPARK = "▁▂▃▄▅▆▇█"


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


def get_signal():
    now = int(time.time())
    window_ts = now - (now % 300)
    
    df = fetch_price()
    if df is None or df.empty:
        return None, 0, 0, 0, False, []
    
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

    direction = "UP 🟢" if score > 0 else "DOWN 🔴"
    confidence = min(100, abs(score) / 8 * 100)

    # ponytail: AI hanya jadi tiebreaker saat sinyal aturan lemah (|score|<=4);
    # delta jendela tetap dominan. Kalau mau AI selalu konsultasi, hapus syarat abs(score).
    ai_used = False
    if AI_API_KEY and abs(score) <= 4:
        ai = ask_ai(delta, cur_price, df["close"].tolist())
        if ai:
            direction, ai_conf = ai
            confidence = max(confidence, min(ai_conf, 70))
            ai_used = True

    return direction, confidence, open_price, cur_price, ai_used, df["close"].tolist()

def main():
    print("Polymarket Signal Bot (No Wallet Mode) - Monitoring...")
    print("-----------------------------------------------------")
    
    last_window = 0
    
    while True:
        try:
            now = int(time.time())
            current_window = now - (now % 300)
            time_into_window = now % 300
            
            # Sinyal dikirim saat 285-299 detik di dalam jendela 5 menit (T-15s s/d T-1s)
            if time_into_window >= 285 and current_window != last_window:
                direction, confidence, op, cp, ai_used, closes = get_signal()
                if direction:
                    # Convert window epoch to ET (EDT = UTC-4)
                    et_window = datetime.utcfromtimestamp(current_window) - timedelta(hours=4)
                    et_str = et_window.strftime("%I:%M %p ET")
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] MARKET: btc-5m-{current_window} ({et_str})")
                    print(f"[{ts}] SIGNAL: {direction} (Conf: {confidence:.1f}%){' [AI]' if ai_used else ''}")
                    print(f"[{ts}] Prices: Open {op:.2f} -> Cur {cp:.2f}")
                    print(f"[{ts}] Chart  : {sparkline(closes[-40:])}")
                    print("-" * 50)
                    last_window = current_window
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Signal failed (Binance error).")
            
            time.sleep(1)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
