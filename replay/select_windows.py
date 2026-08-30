"""Select three non-overlapping 168h (336 x 30m bars) BTC windows for phase-2 backtest.

Classification is by BTC 168h returns over the 180d span:
  - uptrend   : highest positive return window
  - downtrend : most negative return window
  - range     : window with |return| closest to 0
Windows must be fully inside the 180d span, keep >= WARMUP_BARS of data before the
window start (for AlphaZoo warmup, no-lookahead), and be pairwise separated by
MIN_SEPARATION_BARS.

All three coins share the same date windows: select_windows maps each segment's
start/end timestamps onto each coin's bar file (identical fetch alignment), so runs
per (segment, coin) only need index offsets from this file.

Output: replay/data/windows.json
  {"segments": [{name, start_ts, end_ts, btc_ret_pct, btc_max_dd_pct}, ...],
   "coins": {coin: {segment: {start, end}}},   # end exclusive (replay slice convention)
   "files": {coin: path}}
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

WINDOW_BARS = 336            # 168h of 30m bars
WARMUP_BARS = 400            # bars requiring data BEFORE the replay window start
MIN_SEPARATION_BARS = 340    # windows must not overlap / be adjacent
REPLAY_DIR = Path(__file__).resolve().parent / "data"


def _env_int(name: str, default: int | None) -> int | None:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _load_bars(path: Path) -> List[list]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rolling_returns(bars: List[list], window_bars: int = WINDOW_BARS) -> List[float]:
    """return[i] = close[i+window_bars-1]/close[i] - 1 over the window starting at bar i."""
    closes = [float(b[4]) for b in bars]
    out: List[float] = []
    for i in range(0, len(bars) - window_bars + 1):
        out.append(closes[i + window_bars - 1] / closes[i] - 1.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--btc", default=str(REPLAY_DIR / "bars_btc_180d.json"))
    ap.add_argument("--coins", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--out", default=str(REPLAY_DIR / "windows.json"))
    ap.add_argument("--window-days", type=int, default=None)
    ap.add_argument("--window-bars", type=int, default=None)
    ap.add_argument("--warmup-bars", type=int, default=None)
    ap.add_argument("--separation-bars", type=int, default=None)
    args = ap.parse_args()

    if args.window_bars is not None:
        window_bars = args.window_bars
        window_days: int | None = args.window_days
    elif args.window_days is not None:
        window_bars = args.window_days * 48
        window_days = args.window_days
    else:
        env_bars = _env_int("REPLAY_WINDOW_BARS", None)
        env_days = _env_int("REPLAY_WINDOW_DAYS", None)
        if env_bars is not None:
            window_bars = env_bars
            window_days = None
        elif env_days is not None:
            window_bars = env_days * 48
            window_days = env_days
        else:
            window_bars = WINDOW_BARS
            window_days = None

    warmup_bars = args.warmup_bars if args.warmup_bars is not None else _env_int("REPLAY_WARMUP_BARS", WARMUP_BARS)
    assert warmup_bars is not None
    sep_env = _env_int("REPLAY_SEPARATION_BARS", None)
    if args.separation_bars is not None:
        separation_bars = args.separation_bars
    elif sep_env is not None:
        separation_bars = sep_env
    else:
        separation_bars = window_bars + 4

    btc_bars = _load_bars(Path(args.btc))
    n = len(btc_bars)
    replay_offset = 1000  # >= alignment with fetch_bars --warmup-bars 1000
    lo = replay_offset + warmup_bars
    hi = n - window_bars  # window start must satisfy start+window_bars <= n

    rets = _rolling_returns(btc_bars, window_bars)

    def window_return(start: int) -> float:
        return rets[start]

    def window_start_ts(start: int) -> int:
        return int(btc_bars[start][0])

    def window_end_ts(start: int) -> int:
        return int(btc_bars[start + window_bars - 1][0])

    def pick(target: str) -> int:
        candidates = list(range(lo, hi))
        if not candidates:
            raise SystemExit(f"no candidate windows in [{lo}, {hi})")
        if target == "uptrend":
            return max(candidates, key=window_return)
        if target == "downtrend":
            return min(candidates, key=window_return)
        return min(candidates, key=lambda i: abs(window_return(i)))

    picks: Dict[str, int] = {}
    order = ("uptrend", "range", "downtrend")
    for seg in order:
        cand = pick(seg)
        # enforce separation from already picked windows
        while any(abs(cand - p) < separation_bars for p in picks.values()):
            shifted = False
            for i in range(cand + 1, hi):
                if all(abs(i - p) >= separation_bars for p in picks.values()):
                    cand = i
                    shifted = True
                    break
            if not shifted:
                for i in range(cand - 1, lo - 1, -1):
                    if all(abs(i - p) >= separation_bars for p in picks.values()):
                        cand = i
                        shifted = True
                        break
            if not shifted:
                raise SystemExit(f"cannot place separated window for {seg}")
        picks[seg] = cand

    segments = []
    for seg in order:
        start = picks[seg]
        ret_pct = window_return(start) * 100.0
        # BTC MaxDD inside the window (peak-to-trough on closes, % of peak)
        closes = [float(b[4]) for b in btc_bars[start:start + window_bars]]
        peak = closes[0]
        max_dd = 0.0
        for c in closes:
            peak = max(peak, c)
            max_dd = max(max_dd, (peak - c) / peak)
        segments.append({
            "name": seg,
            "start_ts": window_start_ts(start),
            "end_ts": window_end_ts(start),
            "btc_ret_pct": round(ret_pct, 2),
            "btc_max_dd_pct": round(max_dd * 100.0, 2),
        })

    # map timestamps -> per-coin index ranges (end exclusive, replay slice convention)
    coins: Dict[str, Dict[str, Dict[str, int]]] = {}
    files: Dict[str, str] = {}
    for coin in args.coins:
        path = REPLAY_DIR / f"bars_{coin.lower().replace('usdt', '')}_180d.json"
        bars = _load_bars(path)
        ts_list = [int(b[0]) for b in bars]
        files[coin] = str(path)
        coins[coin] = {}
        for seg in segments:
            start = ts_list.index(seg["start_ts"])
            end = ts_list.index(seg["end_ts"]) + 1  # inclusive -> exclusive +1
            coins[coin][seg["name"]] = {"start": start, "end": end}

    out = {
        "segments": segments,
        "coins": coins,
        "files": files,
        "params": {
            "window_days": window_days,
            "window_bars": window_bars,
            "warmup_bars": warmup_bars,
            "separation_bars": separation_bars,
        },
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    for seg in segments:
        s = datetime.fromtimestamp(seg["start_ts"] / 1000, tz=timezone.utc)
        e = datetime.fromtimestamp(seg["end_ts"] / 1000, tz=timezone.utc)
        print(f"{seg['name']:10s} {s:%Y-%m-%d %H:%M} -> {e:%Y-%m-%d %H:%M} "
              f"btc_ret={seg['btc_ret_pct']:+.2f}% max_dd={seg['btc_max_dd_pct']:.2f}%")


if __name__ == "__main__":
    main()