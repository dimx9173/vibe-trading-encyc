"""
Tearsheet 淚表分析 (Phase 5 — 規格書 §7.2)

從決策 JSONL (或 equity 曲線) 產出專業回測淚表:
1. 月度收益熱力圖 (Monthly Returns Heatmap)
2. Top-N 最大回撤事件剖析 (Drawdown Episodes)
3. 多空決策分佈與勝率矩陣

輸出: Markdown 報告 (format_tearsheet) + 結構化 dict (build_tearsheet).
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _load_records(log_path: str) -> List[Dict]:
    records = []
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _account_equity(rec: Dict) -> float:
    acct = rec.get("account", {})
    if isinstance(acct, dict):
        return float(acct.get("equity", acct.get("balance", 0.0)))
    return 0.0


def _account_balance(rec: Dict) -> float:
    acct = rec.get("account", {})
    if isinstance(acct, dict):
        return float(acct.get("balance", 0.0))
    return 0.0


def _locked_margin(rec: Dict) -> float:
    """未返還 margin (平倉返還, 不計虧損) — 與 agent_report 同語義."""
    acct = rec.get("account", {})
    total = 0.0
    for p in (acct.get("positions") or []) if isinstance(acct, dict) else []:
        try:
            total += float(p["entry_price"]) * float(p["position_amount"]) / float(p.get("leverage", 1))
        except (KeyError, TypeError, ValueError):
            continue
    return total


def build_tearsheet(
    log_path: str,
    initial_balance: float = 10_000.0,
    top_n_drawdowns: int = 5,
) -> Dict:
    """建構 Tearsheet 結構化數據.

    Returns:
        {
          "bars": int, "total_pnl": float, "max_drawdown_pct": float,
          "monthly_returns": [{"month": "2026-08", "return_pct": float}, ...],
          "drawdown_episodes": [{"start": ..., "trough": ..., "end": ..., "depth_pct": float, "recovery_bars": int}, ...],
          "decision_dist": {"BUY": n, ...}, "short_ratio": float, "fallback_count": int,
        }
    """
    records = _load_records(log_path)
    if not records:
        return {"bars": 0, "total_pnl": 0.0, "max_drawdown_pct": 0.0,
                "monthly_returns": [], "drawdown_episodes": [], "decision_dist": {},
                "short_ratio": 0.0, "fallback_count": 0}

    # Equity 曲線 (含未返還 margin 校正 — 真實權益)
    eq_curve: List[float] = []
    for rec in records:
        eq_curve.append(_account_equity(rec) + _locked_margin(rec))
    start_eq = eq_curve[0]
    end_eq = eq_curve[-1]
    total_pnl = end_eq - start_eq

    # 月度收益
    monthly: Dict[str, List[float]] = {}
    for rec in records:
        try:
            ts = datetime.fromtimestamp(int(rec["bar_open_ms"]) / 1000, tz=timezone.utc)
        except (KeyError, ValueError):
            continue
        month = ts.strftime("%Y-%m")
        monthly.setdefault(month, []).append(_account_equity(rec) + _locked_margin(rec))
    monthly_returns = []
    for month in sorted(monthly):
        eqs = monthly[month]
        ret = (eqs[-1] - eqs[0]) / eqs[0] * 100 if eqs[0] else 0.0
        monthly_returns.append({"month": month, "return_pct": round(ret, 2)})

    # 最大回撤 (equity 曲線)
    peak = eq_curve[0]
    max_dd = 0.0
    for eq in eq_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

    # Top-N 回撤事件 (峰→谷→修復)
    episodes: List[Dict] = []
    in_dd = False
    peak_i, trough_i, peak_v, trough_v = 0, 0, eq_curve[0], eq_curve[0]
    for i, eq in enumerate(eq_curve):
        if eq >= peak_v:
            # 新高 → 結束前一個回撤
            if in_dd:
                depth = (peak_v - trough_v) / peak_v * 100
                episodes.append({
                    "start": _bar_time(records, peak_i),
                    "trough": _bar_time(records, trough_i),
                    "end": _bar_time(records, i),
                    "depth_pct": round(depth, 2),
                    "recovery_bars": i - peak_i,
                })
                in_dd = False
            peak_v, peak_i = eq, i
        else:
            in_dd = True
            if eq < trough_v:
                trough_v, trough_i = eq, i
    if in_dd:
        depth = (peak_v - trough_v) / peak_v * 100
        episodes.append({
            "start": _bar_time(records, peak_i),
            "trough": _bar_time(records, trough_i),
            "end": _bar_time(records, len(records) - 1),
            "depth_pct": round(depth, 2),
            "recovery_bars": len(records) - 1 - peak_i,
        })
    episodes.sort(key=lambda e: e["depth_pct"], reverse=True)
    drawdown_episodes = episodes[:top_n_drawdowns]

    # 決策分佈 + 做空佔比 + 兜底率
    decision_dist: Dict[str, int] = Counter()
    short_count = 0
    fallback_count = 0
    total_decisions = 0
    for rec in records:
        decision = str(rec.get("decision", "HOLD"))
        decision_dist[decision] += 1
        total_decisions += 1
        upper = decision.upper()
        if "SELL" in upper or "SHORT" in upper:
            short_count += 1
        # 兜底特徵: 固定 fallback 文案 (一期 34.7% 的根源)
        rationale = str(rec.get("rationale", ""))
        if "情绪面、risk表现强劲" in rationale or "评分卡" in rationale and "WEAK_BUY" in decision:
            fallback_count += 1
    short_ratio = short_count / total_decisions * 100 if total_decisions else 0.0

    return {
        "bars": len(records),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "monthly_returns": monthly_returns,
        "drawdown_episodes": drawdown_episodes,
        "decision_dist": dict(decision_dist),
        "short_ratio": round(short_ratio, 1),
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_count / total_decisions * 100, 1) if total_decisions else 0.0,
        "shadow": _build_shadow(records),
    }


def _build_shadow(records: List[Dict]) -> Dict:
    """影子帳戶簡化版 (規格書 §7 影子反思): 反事實決策評估.

    對每根 bar 的決策, 用其後 4 根 bar 的價格變動計算:
    - 實際決策收益 (BUY=做多, SELL=做空, HOLD=0)
    - 反事實做空收益 (若當時開空會怎樣)
    統計: 若全程無腦做空 vs 實際決策 vs 無腦做多 的假設總收益.
    評估改進空間 (多頭偏斜時, 做空反事實收益應顯著).
    """
    if len(records) < 5:
        return {"horizon_bars": 4, "always_short_pnl": 0.0, "always_long_pnl": 0.0,
                "actual_pnl": 0.0, "hold_short_counterfactual": 0.0}
    closes = []
    for rec in records:
        try:
            closes.append(float(rec.get("bar_close", 0.0)))
        except (TypeError, ValueError):
            closes.append(0.0)
    horizon = 4
    always_short = 0.0
    always_long = 0.0
    actual = 0.0
    hold_short_cf = 0.0
    n = len(records)
    for i in range(n - horizon):
        fwd = (closes[i + horizon] - closes[i]) / closes[i] if closes[i] else 0.0
        always_long += fwd
        always_short += -fwd
        decision = str(records[i].get("decision", "HOLD")).upper()
        if "SELL" in decision or "SHORT" in decision:
            actual += -fwd
        elif "BUY" in decision or "LONG" in decision:
            actual += fwd
        elif "HOLD" in decision:
            hold_short_cf += -fwd  # HOLD 時若做空的反事實收益
    return {
        "horizon_bars": horizon,
        "always_short_pnl": round(always_short * 100, 2),
        "always_long_pnl": round(always_long * 100, 2),
        "actual_pnl": round(actual * 100, 2),
        "hold_short_counterfactual": round(hold_short_cf * 100, 2),
    }


def _bar_time(records: List[Dict], idx: int) -> str:
    try:
        return datetime.fromtimestamp(int(records[idx]["bar_open_ms"]) / 1000,
                                      tz=timezone.utc).strftime("%m-%d %H:%M")
    except (KeyError, ValueError, IndexError):
        return "?"


def format_tearsheet(data: Dict) -> str:
    """格式化為 Markdown 淚表報告."""
    if data.get("bars", 0) == 0:
        return "Tearsheet: 無資料"
    lines = [
        "═══════════════════════════════════════════",
        " Tearsheet 淚表 (Phase 5)",
        "═══════════════════════════════════════════",
        f"  Bars: {data['bars']}",
        f"  Total P&L: {data['total_pnl']:+.2f} USDT",
        f"  Max Drawdown: {data['max_drawdown_pct']:.2f}%",
        f"  Short Ratio: {data['short_ratio']:.1f}%",
        f"  Fallback Rate: {data['fallback_rate']:.1f}% ({data['fallback_count']})",
        "",
        "  Monthly Returns Heatmap:",
    ]
    if data["monthly_returns"]:
        for m in data["monthly_returns"]:
            ret = m["return_pct"]
            marker = "🟢" if ret >= 0 else "🔴"
            lines.append(f"    {marker} {m['month']}: {ret:+.2f}%")
    else:
        lines.append("    (無月度資料)")
    lines.append("")
    lines.append("  Top-N Drawdown Episodes:")
    if data["drawdown_episodes"]:
        for i, e in enumerate(data["drawdown_episodes"], 1):
            lines.append(
                f"    #{i} {e['start']} → {e['trough']} → {e['end']} "
                f"(depth {e['depth_pct']:.2f}%, {e['recovery_bars']} bars)")
    else:
        lines.append("    (無回撤事件)")
    lines.append("")
    lines.append("  Decision Distribution:")
    for dec, n in sorted(data["decision_dist"].items(), key=lambda x: -x[1]):
        lines.append(f"    {dec}: {n}")
    lines.append("═══════════════════════════════════════════")
    return "\n".join(lines)
