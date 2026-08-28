# Tutorial: Polymarket BTC 5-Minute Signal Bot

Complete guide for setup, AI configuration, and running the BTC Up/Down signal bot. The bot can be run in **two modes** (set via `AUTO_TRADE` in `.env`):
- `AUTO_TRADE=false` → **SIGNAL-ONLY**: only provides signals, no orders/automated transactions (default mode for this tutorial).
- `AUTO_TRADE=true` → **AUTO-TRADING**: prediction + automatic order execution on Polymarket CLOB (full strategy + FAQ: see [README.md](README.md)).

---

## 1. What This Bot Does

1. Every 5 minutes, Polymarket opens a market `btc-updown-5m-{window_ts}`.
2. The bot reads 1-minute BTCUSDT klines from Binance.
3. The bot generates **three signals**: **URGENT** (if delta >= 0.15% early on), **PREDICTION** at the 2nd minute of the window (T-180s), and **CONFIRMATION** at T-60s before closing (last 1 minute):
   - Technical score: **window delta** (dominant) + **EMA 9**.
   - If the score is weak (`|score| <= 4`), the bot asks the **AI** (9router/coding-fast) as a tiebreaker.
4. Prints direction + confidence + sparkline chart to the terminal.

---

## 2. Prerequisites

- Python 3.9+ (required for `zoneinfo` module).
- Internet access to `data-api.binance.vision` (or other Binance APIs).
- (Optional) AI API key — e.g., from **9router** with `coding-fast` model and base URL `https://api.your-gateway.example/v1`.
- (Optional) Docker + Docker Compose to run via container.

---

## 3. Setup

### 3.1 Clone / Copy Project

```bash
git clone <your-repo>/PolymarketBot.git
cd PolymarketBot
```

### 3.2 Create .env

```bash
cp .env.example .env
```

Fill `.env`:

```env
# AI API (9router / coding-fast)
AI_API_KEY=sk-...replace-with-your-api-key...
AI_BASE_URL=https://api.your-gateway.example/v1
AI_MODEL=coding-fast
```

> `.env` is already in `.gitignore`. Never commit this file — API keys are secret.
>
> Without `AI_API_KEY`, the bot will still run using rule-based signals only (AI disabled).

### 3.3 Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 4. Running

### Method A — Direct with Python

```bash
python signal.py
```

### Method B — Docker

```bash
docker compose up -d --build
```

> **Change interactive settings:** `python3 config.py` — menu to select parameters → enter values → save to `.env` → automatic restart. All values are stored in `.env`.

View logs:

```bash
docker compose logs -f signal
```

Stop:

```bash
docker compose down
```

---

## 5. Reading Output

```
[07:59:45] MARKET: btc-updown-5m-1787702100 (07:55 PM-08:00 PM ET)
[07:59:45] PREDICTION: UP ������ (Prob: 75.0%) [rule]
[07:59:45] Prices: Open 78496.00 -> Cur 78510.00
[07:59:45] Chart  : █▇▇▆▆▆▅▅▄▄▄▅▆▄▅▅▆▆▅▅▅▄▄▄▃▃▃▁▁▁▁▁▁▁▁▁▁▁▁
--------------------------------------------------
```

| Line       | Meaning                                                              |
| ---------- | -------------------------------------------------------------------- |
| `MARKET`   | Market slug and window time range in ET (auto DST).                  |
| `PREDICTION` | Predicted direction + probability (empirical win rate / rule / AI). |
| `Prices`   | Window open price vs current price.                                  |
| `Chart`    | Sparkline for the last 40 minutes (right = current).                 |

Signal sequence per window: **URGENT** (delta ≥ 0.15% in the first 1 minute, optional), **PREDICTION** (2nd minute, T-180s), **CONFIRMATION** (T-60s, last 1 minute — final decision).

---

## 6. How Signals Work

### Rule Score

```python
# Window delta: directly answers the market question
delta = (cur - open) / open * 100
# |delta| > 0.10% -> ±7 | > 0.02% -> ±5 | > 0.005% -> ±3 | > 0.001% -> ±1

# EMA 9
if cur > ema9: score += 1
else:          score -= 1
```

### AI Tiebreaker

- Called only if `|score| <= 4` (rules are not confident).
- Sends a concise summary (delta, 1m/5m/15m trend, last 12 closes) — long prompts cause reasoning models (`deepseek-v4-flash`) to run out of tokens and return empty answers.
- AI is capped at influencing confidence up to 70%.
- Failure/timeout → 1× retry → fallback to rule signal. The bot never stops.

### Anti-whipsaw

CONFIRMATION (T-60s, last 1 minute) **does not instantly flip the direction** of the PREDICTION: if the new direction is opposite but `|delta| < 0.03%`, the direction is held (`[HOLD]`, confidence ≤ 40%). Prices near the open can fluctuate — flip only if the reversal is decisive (≥ 0.03%).

---

## 7. Time & Zone (Important)

- Polymarket uses Unix timestamps divisible by 300 as market slugs.
- Conversion to ET uses `ZoneInfo("America/New_York")` — **automatically** handles DST:
  - August (summer): EDT = UTC−4.
  - December (winter): EST = UTC−5.
- Verification example: window `1787702100` = **Aug 25, 07:55 PM — 08:00 PM ET**.

---

## 8. Troubleshooting

| Symptom                    | Solution                                                                     |
| -------------------------- | ---------------------------------------------------------------------------- |
| `Failed: api.binance.com`  | Network is blocking that domain. Bot uses `data-api.binance.vision` mirror which is now **first in order** — no more error logs in normal operation. |
| `TRADE [SKIP] ... TransportError` | Local DNS blocks `polymarket.com` (sinkhole). Fixed via `extra_hosts` in `docker-compose.yml` — IP pinned directly to Cloudflare. Update if IP changes: `https://1.1.1.1/dns-query?name=<host>&type=A`. |
| `[AI] retry` in log        | Reasoning model timeout/out of tokens — bot retries once then fallbacks.    |
| `[AI] skipped` always      | Check `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` in `.env`. Or disable AI by emptying `AI_API_KEY`. |
| `ModuleNotFoundError: zoneinfo` | Use Python 3.9+ or `pip install tzdata`.                                  |
| Signal never appears       | Bot prints PREDICTION at 2nd minute and CONFIRMATION at last minute; dynamic auto-trade entry starts from 1st minute (every 15s) only if price fits. Check log at 2nd minute. |
| `TRADE [SKIP] ... price too expensive — negative EV` | Price guard rejects expensive entries (best ask > `TRADE_HARD_MAX_ASK`). Details: [README FAQ](README.md). |

---

## 9. Tips

1. **AI is not a substitute for window delta.** When delta is already decisive (> 0.10%), rules win — do not force AI to flip it.
2. **Use appropriate API keys.** Gateway base URL determines the model; ensure `AI_MODEL` is valid for your gateway (e.g., 9router `coding-fast`).
3. **Observe a few windows first.** Note signal accuracy vs actual results before integrating into a real trading bot.
4. **Keep logs.** Redirect output to a file if running in the background: `python signal.py >> signal.log 2>&1`.