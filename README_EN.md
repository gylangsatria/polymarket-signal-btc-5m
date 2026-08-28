# Polymarket BTC 5-Minute Signal Bot

Signal bot for the Polymarket binary market **"BTC Up or Down"** (5 minutes). The bot reads real-time BTC prices from Binance, runs technical analysis + an AI tiebreaker, then **prints UP/DOWN signals** before the 5-minute Polymarket window closes. With `AUTO_TRADE=true`, the CONFIRM signal (final decision) is **executed directly as a market order on the Polymarket CLOB** — USDC funds & positions stay as collateral on Polymarket, **never withdrawn to an external wallet**.

## ⚠️ Risk Warning & Disclaimer

**Read before using this bot.**

- **Not financial advice.** This bot is only an analysis/automation tool — not investment advice, not a profit guarantee. All trading decisions are yours.
- **Past data ≠ future guarantee.** Shown statistics (win rate, probabilities, etc.) are merely empirical historical data. There is no guarantee a signal will be correct next period. Beware of the **gambler's fallacy** — consecutive wins/losses **do not change** the probability of the next outcome; each window is independent.
- **DYOR (Do Your Own Research).** Learn how Polymarket, contracts, fees, and market mechanics work before putting in real money.
- **Don't get complacent.** 5-minute binary market trading is highly volatile; positions can go to zero. Use only money you can afford to lose entirely. Don't chase losses, set your own limits, and stop once it's out of control.
- **All risk & losses are your responsibility**, not the bot maker's. The bot is used **at your own risk** and discretion.

---

## How It Works

Every 5 minutes Polymarket opens a market: "Will BTC be higher/lower than the opening price when the window closes?". The window follows a Unix timestamp divisible by 300.

```
window_ts     = now - (now % 300)          # window start
close_time    = window_ts + 300            # window closes 5 minutes later
market slug   = btc-updown-5m-{window_ts}   # verified from gamma-api
```

The bot emits **three signals per window**: **URGENT** (if delta >= 0.15% in the first minute), **PREDICTION** at minute 2 (T-180s), then **CONFIRM** at T-60s (the last minute) before close. After close, the bot **verifies the result** — the empirical win rate is used as the probability (calibrated per delta bucket).

---

## Architecture

| File        | Content                                                        |
| ----------- | -------------------------------------------------------------- |
| `signal.py` | All logic: Binance data fetch, TA, AI tiebreaker, main loop, auto-trade hook. |
| `trader.py` | Polymarket CLOB auto-trader via the official `polymarket-client` SDK (auth, market lookup, FOK market order). |

### Dependencies

```
requests>=2.31.0     # HTTP to Binance + AI gateway
pandas               # kline manipulation
python-dotenv>=1.0.0 # read .env
polymarket-client    # official Polymarket CLOB SDK (auto-trade)
```

### Tech Stack

| Layer         | Technology                                                        |
| ------------- | ----------------------------------------------------------------- |
| **Language**  | Python 3.11                                                       |
| **Market data** | Binance REST API (real-time BTC price & kline)                  |
| **Analysis**  | pandas — kline, window delta, EMA 9, Wilson estimation            |
| **AI tiebreaker** | OpenAI-compatible endpoint (`AI_API_KEY`/`AI_BASE_URL`) — optional |
| **Trading**   | Polymarket CLOB via official `polymarket-client` SDK (FOK market order) |
| **Runtime**   | Docker + docker-compose (`network_mode: host`)                    |
| **Config**    | `.env` managed through `config.py` (interactive validation)       |

---

## Signal Strategy

### 1. Window Delta (dominant)

The exact same question as the market: "up/down vs the window open price?".

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

**Anti-whipsaw (HOLD):** if CONFIRM (T-60s) reverses direction but `|delta| < 0.03%` (price almost at open), the direction is **held** following the PREDICTION and confidence is capped at 40%. A thin reversal is often noise that could reverse again; only flip if the opposite delta is **decisive** (≥ 0.03%).

---

## Accuracy & Verification

- After the window closes, the bot **verifies** the prediction vs the actual close price (`VERIFY: ... BENAR/SALAH`/TRUE/FALSE) and stores history in `stats.json`.
- Probability = **Wilson estimation** (shrinkage to 50%): conservative with few samples, approaching win rate with many samples. Examples: `1/1 → 60%`, `7/10 → 64%`, `44/48 → 89%` — no more extreme 100%/0% claims from just 1-2 samples.
- Calibration: `|delta|` buckets (decisive/strong/moderate/thin) are used if ≥ 8 samples; otherwise **pool all samples** (more stable); with no samples at all → rule score.
- The same probability drives **both the printed signal and the trade decision** (dynamic entry) — consistent, not overconfident.
- `[HOLD]` at CONFIRM = PREDICTION's direction is kept because a thin reversal (< 0.03%) is treated as noise.

---

## 💛 Donation

This bot is free & open source. If this app helps you, you may support the developer via a donation (voluntary — the bot works fully even without a donation):

```
Network : Polygon  (MATIC / USDC)
Address : 0xc81d0b32455ae87f73b145a71a7d87f57937427f
```

> Make sure to select the **Polygon** network when sending so funds arrive correctly.

- Fresh start: delete `stats.json`. History accumulates across restarts.
