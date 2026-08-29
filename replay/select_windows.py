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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

WINDOW_BARS = 336            # 168h of 30m bars
WARMUP_BARS = 400            # bars requiring data BEFORE the replay window start
MIN_SEPARATION_BARS = 340    # windows must not overlap / be adjacent
REPLAY_DIR = Path(__file__).resolve().parent / "data"


def _load_bars(path: Path) -> List[list]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rolling_returns(bars: List[list]) -> List[float]:
    """return[i] = close[i+WINDOW_BARS-1]/close[i] - 1 over the window starting at bar i."""
    closes = [float(b[4]) for b in bars]
    out: List[float] = []
    for i in range(0, len(bars) - WINDOW_BARS + 1):
        out.append(closes[i + WINDOW_BARS - 1] / closes[i] - 1.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--btc", default=str(REPLAY_DIR / "bars_btc_180d.json"))
    ap.add_argument("--coins", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--out", default=str(REPLAY_DIR / "windows.json"))
    args = ap.parse_args()

    btc_bars = _load_bars(Path(args.btc))
    n = len(btc_bars)
    # bars[:REPLAY_START_OFFSET] is the fetch warmup buffer; windows must leave
    # >= WARMUP_BARS of data before window start to warm indicators.
    replay_offset = 1000  # >= alignment with fetch_bars --warmup-bars 1000
    lo = replay_offset + WARMUP_BARS
    hi = n - WINDOW_BARS  # window start must satisfy start+WINDOW_BARS <= n

    rets = _rolling_returns(btc_bars)

    def window_return(start: int) -> float:
        return rets[start]

    def window_start_ts(start: int) -> int:
        return int(btc_bars[start][0])

    def window_end_ts(start: int) -> int:
        return int(btc_bars[start + WINDOW_BARS - 1][0])

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
        while any(abs(cand - p) < MIN_SEPARATION_BARS for p in picks.values()):
            shifted = False
            for i in range(cand + 1, hi):
                if all(abs(i - p) >= MIN_SEPARATION_BARS for p in picks.values()):
                    cand = i
                    shifted = True
                    break
            if not shifted:
                for i in range(cand - 1, lo - 1, -1):
                    if all(abs(i - p) >= MIN_SEPARATION_BARS for p in picks.values()):
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
        closes = [float(b[4]) for b in btc_bars[start:start + WINDOW_BARS]]
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
            "window_bars": WINDOW_BARS,
            "warmup_bars": WARMUP_BARS,
            "separation_bars": MIN_SEPARATION_BARS,
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