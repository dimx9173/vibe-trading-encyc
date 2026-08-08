"""Fetch historical BTCUSDT 30m bars for the A/B replay harness.

Pulls N days of 30m bars from Binance public REST (no API key) plus a warmup
buffer (for indicator warmup on leg A, which needs ~100 bars of history).

Output: replay/data/bars.json — list of ccxt-style OHLCV tuples
        [open_time_ms, open, high, low, close, volume]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS = 30 * 60 * 1000


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    """Paginated fetch of Binance klines (public, no auth)."""
    out: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        params = (
            f"symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        url = f"{BINANCE_KLINE_URL}?{params}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        out.extend(batch)
        next_open = int(batch[-1][0]) + INTERVAL_MS
        if next_open <= cursor:
            break
        cursor = next_open
        time.sleep(0.15)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="30m")
    ap.add_argument("--days", type=int, default=14, help="replay window length (days)")
    ap.add_argument("--warmup-bars", type=int, default=120, help="extra bars before the window")
    ap.add_argument("--out", default="data/bars.json")
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    # Align end to the last closed 30m bar
    end_ms = now_ms - (now_ms % INTERVAL_MS)
    start_ms = end_ms - (args.days * 24 * 60 * 60 * 1000) - args.warmup_bars * INTERVAL_MS

    raw = fetch_klines(args.symbol, args.interval, start_ms, end_ms)
    bars = [
        [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
        for k in raw
        if int(k[0]) < end_ms  # drop the still-open bar
    ]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bars), encoding="utf-8")

    replay_bars = [b for b in bars if b[0] >= start_ms + args.warmup_bars * INTERVAL_MS]
    print(
        f"Fetched {len(bars)} bars total "
        f"(warmup {len(bars) - len(replay_bars)} + replay {len(replay_bars)}) "
        f"-> {out_path}"
    )
    print(
        f"Replay window: {datetime.fromtimestamp(replay_bars[0][0]/1000, tz=timezone.utc):%Y-%m-%d %H:%M} "
        f"-> {datetime.fromtimestamp(replay_bars[-1][0]/1000, tz=timezone.utc):%Y-%m-%d %H:%M}"
    )


if __name__ == "__main__":
    main()
