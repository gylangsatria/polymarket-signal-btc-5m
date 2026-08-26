"""
trader.py — Auto-trader Polymarket (CLOB) via SDK resmi `polymarket-client`.

Sinyal UP  → beli token YES ("Up").
Sinyal DOWN → beli token NO ("Down").

PENTING: dana TIDAK pernah ditarik ke wallet eksternal. Semua USDC dan posisi
tetap sebagai collateral di dalam Polymarket (perilaku default CLOB) — modul
ini murni membuka posisi, tidak ada kode withdraw.

Konfigurasi (.env):
    AUTO_TRADE=true            # aktifkan trading
    TRADE_AMOUNT_USD=5.0       # nominal per window (USD)
    TRADE_ON_URGENT=false      # true = ikut eksekusi sinyal URGENT (delta kuat)
    TRADE_DRY_RUN=true         # true = hanya cetak rencana order, tanpa eksekusi

Auth pakai POLY_PRIVATE_KEY. API key dan Deposit Wallet diturunkan otomatis
oleh SDK dari private key (tidak perlu POLY_FUNDER_ADDRESS / POLY_API_SECRET /
POLY_API_PASSPHRASE di .env).

`polymarket-client` di-import lazy di dalam fungsi supaya mode signal-only
tetap jalan tanpa SDK terinstall.
"""

import os
import time

from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "").strip()

def _flag(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")

AUTO_TRADE = _flag("AUTO_TRADE")
DRY_RUN = _flag("TRADE_DRY_RUN")
TRADE_ON_URGENT = _flag("TRADE_ON_URGENT")
# Setelah TAKE-PROFIT, berhenti entry di window yang sama (tunggu market berikutnya).
# false = perilaku lama: bisa beli lagi (scalping berulang dalam 1 window).
STOP_AFTER_TAKE_PROFIT = _flag("STOP_AFTER_TAKE_PROFIT", default="true")
# Mode agresif: probabilitas prediksi >= TRADE_MIN_PROB -> langsung FOK,
# lewati guard harga TRADE_MAX_ASK (asal ada likuiditas di book).
AGGRESSIVE = _flag("TRADE_AGGRESSIVE")

try:
    AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", "0").strip() or 0)
except ValueError:
    AMOUNT_USD = 0.0

# Harga masuk maksimal: skip order jika best ask CLOB > ambang (default 0.6).
# Market updown 5m sering hanya punya ask 0.99 (spread MM) — beli di situ EV negatif.
try:
    MAX_ASK_PRICE = float(os.getenv("TRADE_MAX_ASK", "0.6").strip() or 0.6)
except ValueError:
    MAX_ASK_PRICE = 0.6

# Harga masuk HARD — ceiling mutlak SEMUA mode (termasuk agresif): skip jika best ask > ambang.
# Dilengkapi guard EV adaptif (bayar <= prob, di bawah): harga 0.8-0.9 aman dibeli
# hanya jika keyakinan model >= 80-90%. Default 0.85 = tidak pernah bayar > 85ct.
try:
    HARD_MAX_ASK = float(os.getenv("TRADE_HARD_MAX_ASK", "0.85").strip() or 0.85)
except ValueError:
    HARD_MAX_ASK = 0.85

# Harga masuk MINIMUM: skip jika best ask < ambang. Token semurah ini = sisi yang
# pasar sudah yakin kalah — membeli di situ melawan konsensus pasar (hampir pasti hangus).
try:
    MIN_ASK_PRICE = float(os.getenv("TRADE_MIN_ASK", "0.35").strip() or 0.35)
except ValueError:
    MIN_ASK_PRICE = 0.35

# Ambang probabilitas untuk mode agresif (TRADE_AGGRESSIVE=true), dalam persen (0-100).
try:
    MIN_PROB = float(os.getenv("TRADE_MIN_PROB", "60").strip() or 60)
except ValueError:
    MIN_PROB = 60

# Lantai keyakinan MUTLAK (semua mode): jangan pernah entry jika prob < ini.
# Model dengan keyakinan < 50% (atau lebih tinggi) tidak reliable — sering salah arah.
try:
    MIN_PROB_ENTRY = float(os.getenv("TRADE_MIN_PROB_ENTRY", "50").strip() or 50)
except ValueError:
    MIN_PROB_ENTRY = 50

# Take-profit: jual otomatis jika best bid token >= ambang ini.
try:
    SELL_BID_MIN = float(os.getenv("SELL_BID_MIN", "0.95").strip() or 0.95)
except ValueError:
    SELL_BID_MIN = 0.95

# Cut-loss: jual jika best bid <= ambang ini (sisa nilai — daripada hangus 0 saat kalah).
# Ambang rendah (0.25) + jeda awal (MIN_ELAPSED): window 5m sangat volatil di menit 1-2 —
# harga bisa menyapu 0.30-an lalu kembali. Jangan jual di titik rendah sebelum sempat menang.
try:
    SELL_CUT_LOSS = float(os.getenv("SELL_CUT_LOSS", "0.25").strip() or 0.25)
except ValueError:
    SELL_CUT_LOSS = 0.25

# Jangan cut-loss di < N detik pertama sejak entry (market masih mengguncang).
try:
    SELL_CUT_LOSS_MIN_ELAPSED = float(os.getenv("SELL_CUT_LOSS_MIN_ELAPSED", "90").strip() or 90)
except ValueError:
    SELL_CUT_LOSS_MIN_ELAPSED = 90

# Take-profit ROI: jual saat (bid - entry) / entry >= ambang ini (default 10%).
try:
    SELL_ROI_MIN = float(os.getenv("SELL_ROI_MIN", "0.10").strip() or 0.10)
except ValueError:
    SELL_ROI_MIN = 0.10

# Prefix slug market Polymarket: {asset}-updown-{duration}-{window_start_ts}
# (diverifikasi dari gamma-api: "btc-updown-5m-1787709300" = window 01:55-02:00 UTC)
SLUG_PREFIX = "btc-updown-5m"

_client = None


def enabled():
    """True jika auto-trade aktif."""
    return AUTO_TRADE


def trade_on_urgent():
    return TRADE_ON_URGENT


def get_client():
    """SecureClient (sync) — dibuat sekali, koneksi + derivasi API creds otomatis."""
    global _client
    if _client is None:
        if not PRIVATE_KEY:
            raise RuntimeError("POLY_PRIVATE_KEY kosong — isi .env")
        from polymarket import SecureClient

        # wallet=None → SDK memakai Deposit Wallet turunan dari private key.
        # (JANGAN set wallet=POLY_FUNDER_ADDRESS dari .env: kalau address itu
        #  bukan deposit wallet milik key ini, CLOB menolak order dengan
        #  "maker address not allowed, please use the deposit wallet flow".)
        _client = SecureClient.create(
            private_key=PRIVATE_KEY,
        )
    return _client


def pick_token_id(market, up):
    """Pilih token id outcome UP/DOWN berdasarkan LABEL (bukan posisi index)."""
    target = "up" if up else "down"
    for oc in (market.outcomes.yes, market.outcomes.no):
        label = (oc.label or "").strip().lower()
        if label == target:
            return oc.token_id
    return None


def get_best_ask(token_id):
    """Best ask dari CLOB order book. None jika tidak ada penjual sama sekali."""
    import requests

    b = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=10).json()
    asks = b.get("asks") or []
    return min(float(a["price"]) for a in asks) if asks else None


def get_best_bid(token_id):
    """Best bid dari CLOB order book. None jika tidak ada pembeli."""
    import requests

    b = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=10).json()
    bids = b.get("bids") or []
    return max(float(x["price"]) for x in bids) if bids else None


def check_entry(token_id):
    """None jika layak eksekusi, else pesan kenapa skip."""
    ask = get_best_ask(token_id)
    if ask is None:
        return "ask kosong (no liquidity)"
    if ask > MAX_ASK_PRICE:
        return f"ask {ask:.2f} > TRADE_MAX_ASK={MAX_ASK_PRICE}"
    return None


def trade(window_ts, up, prob=None):
    """Eksekusi market order FOK untuk window. Return dict {ok, msg, ...}.

    prob = probabilitas prediksi (%). Jika AGGRESSIVE dan prob >= TRADE_MIN_PROB,
    guard harga TRADE_MAX_ASK dilewati — langsung FOK.
    """
    ts = time.strftime("%H:%M:%S")
    slug = f"{SLUG_PREFIX}-{window_ts}"
    side_txt = "UP" if up else "DOWN"
    aggressive = AGGRESSIVE and prob is not None and prob >= MIN_PROB

    if not AUTO_TRADE:
        return {"ok": False, "msg": "AUTO_TRADE off"}
    if AMOUNT_USD <= 0:
        return {"ok": False, "msg": f"TRADE_AMOUNT_USD={AMOUNT_USD} tidak valid"}
    # Lantai keyakinan mutlak: jangan entry saat model ragu (prob rendah sering salah arah).
    if prob is not None and prob < MIN_PROB_ENTRY:
        return {"ok": False, "msg": f"{slug} skip: prob {prob:.0f}% < TRADE_MIN_PROB_ENTRY={MIN_PROB_ENTRY:.0f}% (keyakinan model terlalu rendah)"}

    try:
        # DRY-RUN: lookup market publik saja — tidak butuh auth, aman untuk uji coba.
        if DRY_RUN:
            from polymarket import PublicClient

            with PublicClient() as pc:
                market = pc.get_market(slug=slug)
            token_id = pick_token_id(market, up)
            if aggressive:
                ask = get_best_ask(token_id)
                print(f"[{ts}] [DRY-RUN] {slug} BUY {side_txt} ${AMOUNT_USD:.2f} "
                      f"token={token_id} (market {market.id}) ask={ask} [AGRESIF prob={prob:.1f}%]")
                return {"ok": True, "msg": "DRY-RUN", "token_id": token_id}
            reason = check_entry(token_id)
            if reason:
                print(f"[{ts}] [DRY-RUN] {slug} BUY {side_txt} SKIP ({reason})")
                return {"ok": False, "msg": "DRY-RUN SKIP", "reason": reason}
            # Guard EV: harga masuk > keyakinan model -> beli rugi terjamin.
            if prob is not None:
                ask = get_best_ask(token_id)
                if ask is not None and ask > prob / 100:
                    print(f"[{ts}] [DRY-RUN] {slug} BUY {side_txt} SKIP "
                          f"(ask {ask:.2f} > prob {prob:.0f}% — EV negatif)")
                    return {"ok": False, "msg": "DRY-RUN SKIP", "reason": "EV negatif"}
                if ask is not None and ask < MIN_ASK_PRICE:
                    print(f"[{ts}] [DRY-RUN] {slug} BUY {side_txt} SKIP "
                          f"(ask {ask:.2f} < TRADE_MIN_ASK={MIN_ASK_PRICE} — sisi kalah)")
                    return {"ok": False, "msg": "DRY-RUN SKIP", "reason": "sisi hampir pasti kalah"}
            print(f"[{ts}] [DRY-RUN] {slug} BUY {side_txt} ${AMOUNT_USD:.2f} "
                  f"token={token_id} (market {market.id})")
            return {"ok": True, "msg": "DRY-RUN", "token_id": token_id}

        client = get_client()
        market = client.get_market(slug=slug)

        if market.state.closed:
            return {"ok": False, "msg": f"market {slug} sudah closed"}
        if market.state.active is False or market.state.accepting_orders is False:
            return {"ok": False, "msg": f"market {slug} tidak menerima order"}

        token_id = pick_token_id(market, up)
        if not token_id:
            return {"ok": False, "msg": f"outcome '{side_txt}' tidak punya token id ({slug})"}

        # Batas HARD: ceiling mutlak — semua mode (termasuk agresif) skip jika harga masuk terlalu mahal.
        ask = get_best_ask(token_id)
        if ask is not None and ask > HARD_MAX_ASK:
            return {"ok": False, "msg": f"{slug} skip: ask {ask:.2f} > TRADE_HARD_MAX_ASK={HARD_MAX_ASK} (harga terlalu mahal — EV negatif)"}
        # Batas MIN: token semurah ini hampir pasti kalah — jangan lawan pasar.
        if ask is not None and ask < MIN_ASK_PRICE:
            return {"ok": False, "msg": f"{slug} skip: ask {ask:.2f} < TRADE_MIN_ASK={MIN_ASK_PRICE} (sisi hampir pasti kalah)"}

        # Guard EV adaptif — berlaku SEMUA mode (termasuk agresif): jangan pernah bayar
        # lebih dari keyakinan model. EV = prob% - ask; bayar @P butuh prob >= P supaya EV >= 0.
        # Ini yang membuat harga 0.7-0.85 tetap bisa dibeli saat model yakin (prob >= ask%),
        # tanpa pernah beli EV negatif.
        if prob is not None and ask is not None and ask > prob / 100:
            return {"ok": False, "msg": f"{slug} skip: ask {ask:.2f} > prob {prob:.0f}% (EV negatif)"}

        if not aggressive:
            reason = check_entry(token_id)
            if reason:
                return {"ok": False, "msg": f"{slug} skip: {reason}"}
        else:
            print(f"[{ts}] agresif: prob={prob:.1f}% >= TRADE_MIN_PROB={MIN_PROB} — FOK (EV guard aktif: bayar <= prob)")

        resp = client.place_market_order(
            token_id=token_id,
            side="BUY",
            amount=str(AMOUNT_USD),
            order_type="FOK",  # all-or-nothing; kalau likuiditas kurang, dibatalkan
        )
        if not resp.ok:
            return {"ok": False, "msg": getattr(resp, "message", "order ditolak")}

        filled = resp.status == "matched"
        print(
            f"[{ts}] TRADE{' FILLED' if filled else ''}: {slug} BUY {side_txt} "
            f"orderID={resp.order_id} status={resp.status} "
            f"spent=${resp.making_amount} got={resp.taking_amount}"
            + (f" txs={list(resp.transactions_hashes)}" if resp.transactions_hashes else "")
        )
        return {
            "ok": True,
            "order_id": resp.order_id,
            "status": resp.status,
            "spent": str(resp.making_amount),
            "token_id": token_id,
            "shares": str(resp.taking_amount),  # BUY: taking_amount = shares diterima
        }
    except Exception as e:
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"}


def sell(token_id, shares):
    """Jual semua shares token (take-profit) via FOK. Return {ok, ...}.

    SELL: taking_amount = USDC diterima.
    """
    ts = time.strftime("%H:%M:%S")
    try:
        client = get_client()
        resp = client.place_market_order(
            token_id=token_id,
            side="SELL",
            shares=str(shares),
            order_type="FOK",
        )
        if not resp.ok:
            return {"ok": False, "msg": getattr(resp, "message", "sell ditolak")}
        print(f"[{ts}] SELL: token={token_id[:12]} shares={shares} status={resp.status} "
              f"received=${resp.taking_amount}")
        return {"ok": True, "status": resp.status, "received": str(resp.taking_amount)}
    except Exception as e:
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"}
