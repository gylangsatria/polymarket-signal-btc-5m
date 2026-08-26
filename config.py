#!/usr/bin/env python3
"""Pengaturan interaktif PolymarketBot — semua nilai disimpan & dibaca dari `.env`.

Cara pakai (di host, folder project):
    python3 config.py

Pilih nomor parameter -> masukkan nilai baru -> validasi -> 0 untuk simpan.
Setelah simpan, tawarkan restart container (docker compose up -d) agar nilai aktif.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

# (key, deskripsi, tipe, min, max)
FIELDS = [
    ("AUTO_TRADE",              "Mode: true = auto-trading, false = signal-only (prediksi saja)", "bool"),
    ("TRADE_AMOUNT_USD",        "Nominal per window (USD) — jangan lebih besar dari saldo deposit", "float", 0.5, 50),
    ("RECHECK_INTERVAL",        "Detik: interval cek harga & posisi (entry/TP/cut-loss)", "float", 2, 60),
    ("TRADE_MAX_ASK",           "Harga masuk maksimal jalur normal", "float", 0.1, 0.95),
    ("TRADE_HARD_MAX_ASK",      "Batas keras SEMUA mode (agresif tetap kena): beli hanya jika ask <= ini", "float", 0.1, 0.95),
    ("TRADE_MIN_ASK",           "Jangan beli token di bawah harga ini (sisi yang pasar yakin kalah)", "float", 0.05, 0.5),
    ("TRADE_AGGRESSIVE",        "Agresif: prob >= TRADE_MIN_PROB langsung FOK (lewati TRADE_MAX_ASK)", "bool"),
    ("TRADE_MIN_PROB",          "Ambang probabilitas mode agresif (%)", "int", 50, 100),
    ("SELL_ROI_MIN",            "Take-profit ROI minimal (0.10 = +10%)", "float", 0.0, 1.0),
    ("SELL_CUT_LOSS",           "Cut-loss: jual jika best bid <= ambang ini", "float", 0.0, 0.6),
    ("SELL_CUT_LOSS_MIN_ELAPSED", "Jangan cut-loss di < N detik pertama sejak entry", "float", 0, 240),
    ("STOP_AFTER_TAKE_PROFIT",  "Setelah take-profit: berhenti di window itu (tunggu market berikutnya)", "bool"),
    ("TRADE_ON_URGENT",         "Eksekusi juga sinyal URGENT (delta >= 0.15%)", "bool"),
    ("TRADE_DRY_RUN",           "DRY-RUN: cetak rencana order tanpa eksekusi", "bool"),
]


def load_env():
    """Baca .env menjadi (baris asli, dict key->value). Komentar baris dipertahankan."""
    lines = []
    pairs = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for ln in f:
                lines.append(ln.rstrip("\n"))
                s = ln.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, _, v = s.partition("=")
                    pairs[k.strip()] = v.strip()
    return lines, pairs


def set_value(lines, key, value):
    """Ganti nilai key di .env (pertahankan indentasi & komentar trailing); tambah bila belum ada."""
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#") or "=" not in s:
            continue
        if s.split("=", 1)[0].strip() == key:
            indent = ln[: len(ln) - len(ln.lstrip())]
            comment = ""
            if "#" in ln:
                comment = " #" + ln.split("#", 1)[1]
            lines[i] = f"{indent}{key}={value}{comment}"
            return
    lines.append(f"{key}={value}")


def ask_bool(name, cur):
    while True:
        raw = input(f"  nilai baru untuk {name} (true/false) [{cur}]: ").strip().lower()
        if not raw:
            return str(cur)
        if raw in ("true", "1", "yes", "on"):
            return "true"
        if raw in ("false", "0", "no", "off"):
            return "false"
        print("  harus true atau false.")


def ask_number(name, cur, kind, lo, hi):
    while True:
        raw = input(f"  nilai baru untuk {name} [{cur}] (rentang {lo}-{hi}): ").strip()
        if not raw:
            return str(cur)
        try:
            v = float(raw)
            if kind == "int":
                v = int(v)
            if not (lo <= v <= hi):
                print(f"  di luar rentang {lo}-{hi}.")
                continue
            return str(v)
        except ValueError:
            print(f"  harus angka{' bulat' if kind == 'int' else ''}.")


def main():
    lines, pairs = load_env()

    def cur(k):
        return pairs.get(k, "—")

    print("=" * 62)
    print("  PolymarketBot — Pengaturan Interaktif (disimpan di .env)")
    print("=" * 62)
    print("  Ubah nilai, lalu pilih 0 untuk simpan & (opsional) restart.")
    print()
    while True:
        print("  Parameter:")
        for i, f in enumerate(FIELDS, 1):
            key, desc, *_ = f
            print(f"  {i:2d}. {key:<28} = {cur(key):>8}   {desc}")
        print("   0. Simpan & selesai")
        print()
        choice = input("  Pilih nomor: ").strip()
        if choice == "0":
            break
        if not choice.isdigit() or not (1 <= int(choice) <= len(FIELDS)):
            print("  Pilihan tidak valid.\n")
            continue
        key, desc, kind, *rng = FIELDS[int(choice) - 1]
        lo, hi = (rng + [None, None])[:2] if rng else (None, None)
        print(f"\n  {key}: {desc}")
        if kind == "bool":
            new = ask_bool(key, cur(key))
        else:
            new = ask_number(key, cur(key), kind, lo, hi)
        set_value(lines, key, new)
        pairs[key] = new
        print(f"  -> {key} = {new}\n")

    with open(ENV_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n  Tersimpan ke {ENV_PATH}")

    if os.path.exists(os.path.join(HERE, "docker-compose.yml")):
        ans = input("  Restart container sekarang agar aktif? (y/n) [y]: ").strip().lower()
        if ans not in ("n", "no", "0"):
            print("  docker compose up -d ...")
            subprocess.run(["docker", "compose", "up", "-d"], cwd=HERE)
            print("  Selesai. Cek: docker logs -f polymarketbot-signal-1")
        else:
            print("  Restart nanti: docker compose up -d")
    else:
        print("  Restart nanti: docker compose up -d")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nDibatalkan — .env tidak diubah.")
        sys.exit(1)
