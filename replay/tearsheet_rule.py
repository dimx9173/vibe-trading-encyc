"""Phase-2 3x168h tearsheet (收敛计划 §4 gate: 每段 PF≥1.2, 总 MaxDD≤5%).

Reads per-(segment, coin) rule-engine replay JSONL (s2_{seg}_{coin}_decisions.jsonl)
produced by run_phase2.py, then aggregates the three coin accounts into a segment
portfolio (3 x 10k = 30k) and computes:

  - equity curve   : per-coin rec["account"]["equity"]  (cash + locked margin +
                     unrealized — 保证金不计入亏损, 修复 PnL 高估前科)
  - PF             : Σ+Δrealized / |Σ-Δrealized| (realized-only, standard)
  - win rate / payoff : per-bar realized-delta classification
  - MaxDD          : per-coin (on 10k) and segment/combined (on 30k)
  - total MaxDD    : concatenated segment PnL curves in chronological order

Gate (Q7): every segment PF >= 1.2 AND combined MaxDD <= 5% (on 30k) AND
every per-coin MaxDD <= 5% (on 10k). Prints PASS/FAIL.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

SEGMENT_ORDER = ["range", "downtrend", "uptrend"]  # chronological by start date
INITIAL = 10_000.0


def _load(seg: str, coin: str, data_dir: Path) -> List[dict]:
    tag = f"s2_{seg}_{coin.lower().replace('usdt', '')}"
    path = data_dir / f"{tag}_decisions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _max_drawdown_pct(equity: List[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return max_dd * 100.0


def _metrics(recs: List[dict]) -> dict:
    """Per coin: equity curve + realized deltas from cumulative realized."""
    realized_prev = 0.0
    deltas: List[float] = []
    equity: List[float] = []
    opens = 0
    closes = 0
    for r in recs:
        acct = r.get("account", {})
        realized = float(acct.get("realized", 0.0))
        deltas.append(realized - realized_prev)
        realized_prev = realized
        equity.append(float(acct.get("equity", INITIAL)))
        act = r.get("action", "")
        if act == "open":
            opens += 1
        elif act in ("exit", "reduce"):
            closes += 1
    return {"equity": equity, "deltas": deltas, "opens": opens, "closes": closes}


def _segment_stats(recs_by_coin: Dict[str, List[dict]]) -> dict:
    coins = {c: _metrics(v) for c, v in recs_by_coin.items() if v}
    n = max((len(m["equity"]) for m in coins.values()), default=0)
    seg_equity: List[float] = [
        sum((coins[c]["equity"][i] if i < len(coins[c]["equity"]) else INITIAL)
            for c in coins) for i in range(n)
    ]
    all_deltas = [d for c in coins for d in coins[c]["deltas"]]
    gross_profit = sum(d for d in all_deltas if d > 0)
    gross_loss = abs(sum(d for d in all_deltas if d < 0))
    wins = [d for d in all_deltas if d > 0]
    losses = [d for d in all_deltas if d < 0]
    traded = len(wins) + len(losses)
    pf = gross_profit / gross_loss if gross_loss > 1e-9 else (float("inf") if gross_profit > 1e-9 else 0.0)
    win_rate = len(wins) / traded if traded else 0.0
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else 0.0
    return {
        "n_bars": n,
        "opens": sum(coins[c]["opens"] for c in coins),
        "closes": sum(coins[c]["closes"] for c in coins),
        "final_equity": seg_equity[-1] if seg_equity else len(coins) * INITIAL,
        "return_pct": (seg_equity[-1] - len(coins) * INITIAL) / (len(coins) * INITIAL) * 100.0 if seg_equity else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "pf": pf,
        "win_rate": win_rate,
        "payoff": payoff,
        "trades": traded,
        "max_dd_pct": _max_drawdown_pct(seg_equity),
        "coins_max_dd_pct": {c: _max_drawdown_pct(coins[c]["equity"]) for c in coins},
        "equity": seg_equity,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parent / "data"))
    ap.add_argument("--windows", default=None)
    ap.add_argument("--json", action="store_true", help="machine-readable summary (sweep 用)")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    windows_path = Path(args.windows) if args.windows else data_dir / "windows.json"
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    coins = list(windows["files"].keys())
    seg_meta = {s["name"]: s for s in windows["segments"]}

    stats: Dict[str, dict] = {}
    combined_pnl: List[float] = []
    for seg in SEGMENT_ORDER:
        meta = seg_meta.get(seg)
        if meta is None:
            continue
        recs_by_coin = {c: _load(seg, c, data_dir) for c in coins}
        st = _segment_stats(recs_by_coin)
        stats[seg] = st
        base = len(coins) * INITIAL
        combined_pnl.extend(e - base for e in st["equity"])

    total_equity = [len(coins) * INITIAL + p for p in combined_pnl]
    total_max_dd = _max_drawdown_pct(total_equity) if total_equity else 0.0

    if args.json:
        out = {
            "segments": {
                seg: {
                    "pf": round(st["pf"], 4) if st["pf"] != float("inf") else None,
                    "pf_inf": st["pf"] == float("inf"),
                    "trades": st["trades"], "opens": st["opens"],
                    "return_pct": round(st["return_pct"], 4),
                    "max_dd_pct": round(st["max_dd_pct"], 4),
                    "win_rate": round(st["win_rate"], 4),
                }
                for seg, st in stats.items()
            },
            "total_max_dd_pct": round(total_max_dd, 4),
            "gate_pass": all(
                (st["pf"] >= 1.2 or st["pf"] == float("inf")) and st["trades"] > 0
                and not any(v > 5.0 for v in st["coins_max_dd_pct"].values())
                for st in stats.values()
            ) and total_max_dd <= 5.0,
        }
        print(json.dumps(out))
        return

    print("=" * 88)
    print(f"{'segment':10s} {'window':34s} {'BTCret%':>8s} {'opens':>5s} {'closes':>6s} "
          f"{'ret%':>7s} {'PF':>6s} {'win%':>6s} {'payoff':>7s} {'MaxDD%':>7s} {'coin-MaxDD%(BTC/ETH/SOL)':>22s}")
    print("-" * 88)
    pf_ok = True
    for seg in SEGMENT_ORDER:
        if seg not in stats:
            continue
        st = stats[seg]
        meta = seg_meta[seg]
        s = datetime.fromtimestamp(meta["start_ts"] / 1000, tz=timezone.utc)
        e = datetime.fromtimestamp(meta["end_ts"] / 1000, tz=timezone.utc)
        pf_s = f"{st['pf']:.2f}" if st["pf"] != float("inf") else "inf"
        coin_dd = "/".join(f"{st['coins_max_dd_pct'].get(c, 0.0):.2f}" for c in coins)
        print(f"{seg:10s} {s:%m-%d %H:%M}->{e:%m-%d %H:%M} {meta['btc_ret_pct']:>7.2f}% "
              f"{st['opens']:>5d} {st['closes']:>6d} {st['return_pct']:>6.2f}% {pf_s:>6s} "
              f"{st['win_rate']*100:>5.1f}% {st['payoff']:>7.2f} {st['max_dd_pct']:>6.2f}% "
              f"{coin_dd:>22s}")
        if st["pf"] < 1.2 and st["trades"] > 0:
            pf_ok = False
        if st["trades"] == 0:
            pf_ok = False
        if any(v > 5.0 for v in st["coins_max_dd_pct"].values()):
            pf_ok = False
    print("-" * 88)
    print(f"total MaxDD (combined 30k portfolio): {total_max_dd:.2f}%  "
          f"[gate <= 5%]  {'PASS' if total_max_dd <= 5.0 else 'FAIL'}")
    print(f"per-segment PF >= 1.2 (with trades):  {'PASS' if pf_ok else 'FAIL'}")
    print("=" * 88)
    ok = pf_ok and total_max_dd <= 5.0
    print(f"PHASE-2 GATE: {'PASS ✅' if ok else 'FAIL ❌'} "
          f"(收敛计划 Q7: 每段各自 PF>=1.2, 总 MaxDD<=5%)")


if __name__ == "__main__":
    main()