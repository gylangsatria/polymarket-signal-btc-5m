# Polymarket BTC 5-Minute Signal Bot

Signal bot for Polymarket "BTC Up or Down" (5-minute) binary market. The bot reads real-time BTC prices from Binance, performs technical analysis + AI tiebreaker, and **prints UP/DOWN signals** before the Polymarket 5-minute window closes. With `AUTO_TRADE=true`, the CONFIRMATION signal (final decision) is **instantly executed as a market order on the Polymarket CLOB** — USDC funds and positions remain as collateral on Polymarket, **never withdrawn to an external wallet**.

## ⚠️ Risk Warning & Disclaimer

**Read before using this bot.**

- **Not financial advice.** This bot is only an analysis/automation tool — not investment advice, not a profit guarantee. All trading decisions rest with you.
- **Past performance ≠ future results.** Displayed statistics (win rate, probabilities, etc.) are merely empirical historical data. No guarantee of correct signals going forward. Beware of the **gambler's fallacy** — a streak of wins/losses **does not change** the probability of the next outcome; each window is independent.
- **DYOR (Do Your Own Research).** Study how Polymarket works — contracts, fees, and market mechanics — before staking real money.
- **Don't bet beyond your means.** 5-minute binary markets are extremely volatile; positions can go to zero. Use only funds you can afford to lose entirely. Never chase losses; set your own limits and stop when out of control.
- **All risk & loss are your responsibility**, not the bot author's. The bot is used **at your own risk** and discretion.


---

## How It Works

Every 5 minutes, Polymarket opens a market: "Will BTC be higher/lower than the open price when the window closes?". The window follows Unix timestamps divisible by 300.

```
window_ts     = now - (now % 300)          # window start
close_time    = window_ts + 300            # window closes 5 minutes later
market slug   = btc-updown-5m-{window_ts}   # verified via gamma-api
```

The bot generates **three signals per window**: **URGENT** (if delta >= 0.15% in the first minute), **PREDICTION** at the 2nd minute (T-180s), and **CONFIRMATION** at T-60s (last minute) before closing. After closing, the bot **verifies the result** — empirical win rate is used as probability (calibrated per delta bucket).

---

## Architecture

| File         | Content                                                               |
| ------------ | --------------------------------------------------------------------- |
| `signal.py`  | All logic: Binance data fetch, TA, AI tiebreaker, main loop, auto-trade hook. |
| `trader.py`  | Polymarket CLOB auto-trader via official `polymarket-client` SDK (auth, market lookup, FOK market order). |

### Dependencies

```
requests>=2.31.0     # HTTP to Binance + AI gateway
pandas               # kline manipulation
python-dotenv>=1.0.0 # read .env
polymarket-client    # Official Polymarket CLOB SDK (auto-trade)
```

### Tech Stack

| Layer            | Technology                                                       |
| ---------------- | ---------------------------------------------------------------- |
| **Language**     | Python 3.11                                                      |
| **Market data**  | Binance REST API (real-time BTC price & kline)                   |
| **Analysis**     | pandas — kline, window delta, EMA 9, Wilson estimation           |
| **AI tiebreaker** | OpenAI-compatible endpoint (`AI_API_KEY`/`AI_BASE_URL`) — optional |
| **Trading**      | Polymarket CLOB via official `polymarket-client` SDK (FOK market order) |
| **Runtime**      | Docker + docker-compose (`network_mode: host`)                   |
| **Config**       | `.env` managed through `config.py` (interactive validation)      |

---

## Signal Strategy

### 1. Window Delta (Dominant)

Exactly the same question as the market: "up/down vs window open price?".

```
delta = (current_price - window_open) / window_open * 100

> 0.10%  → score ±7 (almost certain)
> 0.02%  → score ±5 (strong)
> 0.005% → score ±3 (moderate)
> 0.001% → score ±1 (thin)
```

### 2. EMA 9

`current > EMA9` → score +1, otherwise −1.

Total score > 0 → **UP 🟢**, < 0 → **DOWN 🔴**. Confidence = `|score|/8 × 100%`, **capped at max 80%** — a 1-minute prediction never deserves a 100% claim.

**Anti-whipsaw (HOLD):** if CONFIRMATION (T-60s) changes direction but `|delta| < 0.03%` (price near open), the direction is **held** from the PREDICTION and confidence is capped at 40%. Small reversals are often noise that can flip back; only flip if delta is **decisively** opposite (≥ 0.03%).

---

## Accuracy & Verification

- After the window closes, the bot **verifies** the prediction vs the actual close price (`VERIFY: ... CORRECT/WRONG`) and saves the history in `stats.json`.
- Probability = **Wilson estimate** (shrinkage towards 50%): conservative with small samples, approaches win rate with large samples. Example: `1/1 → 60%`, `7/10 → 64%`, `44/48 → 89%` — no more extreme 100%/0% claims from 1-2 samples.
- Calibration: `|delta|` buckets (decisive/strong/moderate/thin) are used if ≥ 8 samples; otherwise, **pooling all samples** (more stable); if no samples exist → rule-based score.
- The same probability is used for **printed signals AND trade decisions** (dynamic entry) — consistent, not overconfident.
- `[HOLD]` in CONFIRMATION = PREDICTION direction is maintained because small reversals (< 0.03%) are considered noise.
- Start fresh: delete `stats.json`. History accumulates across restarts.

---

## FAQ (Auto-Trading)

### 1. Why `TRADE [SKIP]: prob 25% (negative EV)`?
Guard against low-probability trades. `prob 25% (negative EV)` means the price is 82¢ but model confidence is only 25% — paying 0.82 to win only +18% but losing −100% = guaranteed loss. Bot only enters if **prob ≥ `TRADE_MIN_PROB_ENTRY` (50)**, `ask ≤ prob%` (EV ≥ 0) and `ask ≤ 0.85`. Prices 0.8–0.9 **can** be bought when the model is very confident (prob 85–90%) — that is positive EV. Trading less frequently but each trade having an edge — intentional.

### 2. Why `TRADE [SKIP]: ask 0.62 > prob 50% (negative EV)`?
Normal path EV guard: price 0.62 is more expensive than model confidence (50%) — buying that is a statistically guaranteed loss. Correct skip.

### 3. Why cut-loss even if prediction was correct?
The 5m window is highly volatile in the first 1-2 minutes — price can sweep 0.30s then return (actual case: cut @0.36 but window ended CORRECT). Two layers of protection are in place: `SELL_CUT_LOSS` lowered to 0.25 (sell only when truly dead) and `SELL_CUT_LOSS_MIN_ELAPSED=90` (first 90s since entry bot HOLDs). Remaining cut-losses (after 90s, bid ≤ 0.25, or CONFIRMATION flip) are correct decisions.

### 4. Why `not enough balance: balance 1812095, order amount 2060190`?
Polymarket wallet deposit balance (< $1.81) is smaller than order nominal ($2.06). Top-up USDC at polymarket.com, or lower `TRADE_AMOUNT_USD` in `.env`. Numbers use 1e-6 units: `1812095` = $1.812.

### 5. How to switch between signal-only and auto-trading?
Change `AUTO_TRADE` in `.env` → `docker compose up -d` (no rebuild needed):
- `false` = SIGNAL-ONLY (prediction only, no orders)
- `true` = AUTO-TRADING ($`TRADE_AMOUNT_USD` per window)
Log header shows mode: `[AUTO-TRADE, $1.00/window]` vs `[signal-only]`.

### 6. Why does the bot stop trading after 1 profit or 1 loss?
`STOP_AFTER_TAKE_PROFIT=true` (default) and `stopped` after cut-loss — **1 trade per window** is intentional: lock in one clean profit (or limit one loss) then wait for the next 5-minute market. Set `STOP_AFTER_TAKE_PROFIT=false` if you want to scalp within one window.

### 7. Can funds be withdrawn to an external wallet?
Never. All USDC & tokens remain as **collateral on Polymarket** (default CLOB). To check positions/balance, open polymarket.com or use `client.list_positions(...)`.

### 8. Why `SKIP entry ... opposite direction — wait for trend`?
The bot refuses to enter when the prediction is against the current price trend (e.g., UP prediction but price is currently dropping). Anti-whipsaw — waits until signal & trend align.

### 9. How to ensure container uses latest code (stale image)?
Old bug: `docker compose up -d --build` might finish building image but old container remains (kill timeout). Check:
```bash
docker inspect $(docker ps -q -f name=polymarketbot-signal) --format '{{.Image}}'
docker images polymarket-signal --format '{{.ID}}'
```
If different: `docker compose down && docker compose up -d`.

### 10. What is FOK (fill-or-kill)?
Market order that only executes if the entire nominal is filled immediately; otherwise, cancelled — no hanging partial positions. Remaining funds return to deposit wallet.

---

## Key Lessons

1. **Window delta is king.** Short-term TA (EMA, RSI) is very noisy on a 5-minute scale. Delta vs window open price is the direct answer to the market's question.
2. **Entry timing is everything.** PREDICTION at T-180s (large margin, direction not yet locked) → CONFIRMATION at T-60s (last 1 minute, direction more locked). Act based on empirical probability numbers, not just direction.
3. **AI is only supplementary.** Don't let AI flip the signal when delta is already decisive — it just adds noise.
---

## 💛 Donations

This bot is free and open source. If it helps you, you may support the developer with a donation (optional — the bot works fully even without one):

```
Network : Polygon  (MATIC / USDC)
Address : 0xc81d0b32455ae87f73b145a71a7d87f57937427f
```

> Make sure to select the **Polygon** network when sending so the funds arrive correctly.

4. **Binance rate limits are real.** Bot retries automatically; if it fails often, reduce fetch frequency.