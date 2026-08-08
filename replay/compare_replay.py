"""A/B replay comparison report.

Lines up leg A and leg B replay decision logs on the same bar_open_ms,
computes equity curves and P&L stats over the replay window.

Usage:
    python replay/compare_replay.py \
        --a ~/project/vibe-trading/replay/data/leg_a_decisions.jsonl \
        --b ~/project/vibe-trading-hkuds/replay/data/leg_b_decisions.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def load_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def equity_curve(records: list[dict]) -> list[tuple[int, float]]:
    """bar_open_ms -> equity (last record per bar wins)."""
    by_bar: dict[int, dict] = {}
    for r in records:
        by_bar[int(r["bar_open_ms"])] = r
    curve = []
    for bar_ms in sorted(by_bar):
        r = by_bar[bar_ms]
        acct = r.get("account", {})
        if isinstance(acct, dict) and "equity" in acct:
            eq = float(acct["equity"])
        elif isinstance(acct, dict) and "balance" in acct:
            eq = float(acct["balance"])
        else:
            eq = 10000.0
        curve.append((bar_ms, eq))
    return curve


def summarize(name: str, records: list[dict]) -> dict:
    curve = equity_curve(records)
    if not curve:
        return {"name": name, "error": "no records"}
    start_eq = curve[0][1]
    end_eq = curve[-1][1]
    decisions = [r.get("decision", "HOLD") for r in records]
    buys = sum(1 for d in decisions if d in ("BUY", "STRONG BUY", "WEAK BUY"))
    sells = sum(1 for d in decisions if d in ("SELL", "STRONG SELL", "WEAK SELL"))
    max_eq = max(e for _, e in curve)
    min_eq = min(e for _, e in curve)
    return {
        "name": name,
        "bars": len(curve),
        "start_equity": round(start_eq, 2),
        "end_equity": round(end_eq, 2),
        "pnl": round(end_eq - 10000.0, 2),
        "pnl_pct": round((end_eq / 10000.0 - 1) * 100, 2),
        "max_equity": round(max_eq, 2),
        "min_equity": round(min_eq, 2),
        "max_drawdown_pct": round((1 - min_eq / max(max_eq, 1e-9)) * 100, 2),
        "buys": buys,
        "sells": sells,
        "holds": len(decisions) - buys - sells,
        "first_bar": datetime.fromtimestamp(curve[0][0] / 1000, tz=timezone.utc).strftime("%m-%d %H:%M"),
        "last_bar": datetime.fromtimestamp(curve[-1][0] / 1000, tz=timezone.utc).strftime("%m-%d %H:%M"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="~/project/vibe-trading/replay/data/leg_a_decisions.jsonl")
    ap.add_argument("--b", default="~/project/vibe-trading-hkuds/replay/data/leg_b_decisions.jsonl")
    args = ap.parse_args()

    a_recs = load_log(Path(args.a).expanduser())
    b_recs = load_log(Path(args.b).expanduser())
    a_sum = summarize("A (vibe-trading)", a_recs)
    b_sum = summarize("B (hkuds)", b_recs)

    print("=" * 62)
    print("A/B replay comparison — past two weeks")
    print("=" * 62)
    for s in (a_sum, b_sum):
        if "error" in s:
            print(f"{s['name']}: {s['error']}")
            continue
        print(f"\n[{s['name']}]  bars={s['bars']}  {s['first_bar']} -> {s['last_bar']}")
        print(f"  Equity: {s['start_equity']} -> {s['end_equity']}  "
              f"(PnL {s['pnl']:+} USDT, {s['pnl_pct']:+.2f}%)")
        print(f"  Max equity {s['max_equity']} / Min {s['min_equity']}  "
              f"(max DD {s['max_drawdown_pct']:.2f}%)")
        print(f"  Decisions: BUY x{s['buys']}  SELL x{s['sells']}  HOLD x{s['holds']}")

    if "error" not in a_sum and "error" not in b_sum:
        delta = b_sum["pnl"] - a_sum["pnl"]
        leader = "B" if delta > 0 else ("A" if delta < 0 else "tie")
        print(f"\n{'=' * 62}")
        print(f"🏆 Leader: leg {leader}  (Δ PnL {abs(delta):.2f} USDT)")


if __name__ == "__main__":
    main()
