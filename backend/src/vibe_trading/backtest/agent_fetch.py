"""Fetch historical bars for agent replay (productized from replay/fetch_bars.py).

Pulls N days of klines from Binance public REST (no API key) plus a warmup
buffer (for indicator warmup, ~100 bars of history).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import urllib.request

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS_MAP = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def _fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> List[List[Any]]:
    """Paginated fetch of Binance klines (public, no auth)."""
    interval_ms = INTERVAL_MS_MAP.get(interval, 30 * 60 * 1000)
    out: List[List[Any]] = []
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
        next_open = int(batch[-1][0]) + interval_ms
        if next_open <= cursor:
            break
        cursor = next_open
        time.sleep(0.15)
    return out


def fetch_bars(
    symbol: str = "BTCUSDT",
    interval: str = "30m",
    days: int = 14,
    warmup_bars: int = 120,
    out: str = "replay/data/bars.json",
) -> str:
    """Fetch bars and write to out path. Returns the output path."""
    interval_ms = INTERVAL_MS_MAP.get(interval, 30 * 60 * 1000)
    now_ms = int(time.time() * 1000)
    end_ms = now_ms - (now_ms % interval_ms)  # align to last closed bar
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000) - warmup_bars * interval_ms

    raw = _fetch_klines(symbol, interval, start_ms, end_ms)
    bars = [
        [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
        for k in raw
        if int(k[0]) < end_ms  # drop the still-open bar
    ]
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bars), encoding="utf-8")

    replay_bars = [b for b in bars if b[0] >= start_ms + warmup_bars * interval_ms]
    print(
        f"Fetched {len(bars)} bars total "
        f"(warmup {len(bars) - len(replay_bars)} + replay {len(replay_bars)}) "
        f"-> {out_path}"
    )
    if replay_bars:
        print(
            f"Replay window: {datetime.fromtimestamp(replay_bars[0][0]/1000, tz=timezone.utc):%Y-%m-%d %H:%M} "
            f"-> {datetime.fromtimestamp(replay_bars[-1][0]/1000, tz=timezone.utc):%Y-%m-%d %H:%M}"
        )
    return str(out_path)
