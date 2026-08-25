import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

BINANCE_URLS = [
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",  # public mirror
]

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


def get_signal():
    now = int(time.time())
    window_ts = now - (now % 300)
    
    df = fetch_price()
    if df is None or df.empty:
        return None, 0, 0, 0
    
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
    
    return direction, confidence, open_price, cur_price

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
                direction, confidence, op, cp = get_signal()
                if direction:
                    # Convert window epoch to ET (EDT = UTC-4)
                    et_window = datetime.utcfromtimestamp(current_window) - timedelta(hours=4)
                    et_str = et_window.strftime("%I:%M %p ET")
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] MARKET: btc-5m-{current_window} ({et_str})")
                    print(f"[{ts}] SIGNAL: {direction} (Conf: {confidence:.1f}%)")
                    print(f"[{ts}] Prices: Open {op:.2f} -> Cur {cp:.2f}")
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
