#!/usr/bin/env python
"""Phase 5 — 4.2 KPI 驗證腳本 (規格書 §9 L2 達標標準).

398-Bar Replay V3 完成後執行: 驗證 6 項 KPI 並產出 Tearsheet 淚表報告.

用法:
    python -m vibe_trading.replay.verify_kpis <log_path>
"""
import sys
from pathlib import Path

from vibe_trading.replay.tearsheet import build_tearsheet, format_tearsheet

KPIS = [
    ("做空決策佔比 (Short Ratio)", 25.0, 45.0, "%"),
    ("總體淨盈虧 (PnL)", None, None, "USDT"),  # 目標 > 0
    ("最大回撤 (MDD)", None, 3.0, "%"),
    ("評分卡兜底率 (Fallback Rate)", None, 5.0, "%"),
]


def verify(log_path: str) -> dict:
    ts = build_tearsheet(log_path)
    if ts["bars"] == 0:
        return {"ok": False, "error": "無資料"}
    results = {}
    # 1. Short ratio 25-45%
    sr = ts["short_ratio"]
    results["short_ratio"] = {"value": sr, "pass": 25.0 <= sr <= 45.0}
    # 2. PnL 轉正 (> 0, 目標 +3%~+8%)
    pnl = ts["total_pnl"]
    results["total_pnl"] = {"value": pnl, "pass": pnl > 0}
    # 3. MDD < 3%
    mdd = ts["max_drawdown_pct"]
    results["max_drawdown"] = {"value": mdd, "pass": mdd < 3.0}
    # 4. Fallback rate < 5%
    fb = ts["fallback_rate"]
    results["fallback_rate"] = {"value": fb, "pass": fb < 5.0}
    # 5. 平均 R:R (從決策 rational 無法直接算 — 用 shadow 反事實作參考)
    shadow = ts.get("shadow", {})
    results["shadow"] = shadow
    return results


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else "replay/data/replay_v3_decisions.jsonl"
    if not Path(log_path).exists():
        print(f"❌ 找不到回測輸出: {log_path}")
        sys.exit(1)
    ts = build_tearsheet(log_path)
    print(format_tearsheet(ts))
    print()
    print("════════ KPI 驗證 (規格書 §9 L2) ════════")
    results = verify(log_path)
    if "error" in results:
        print("❌", results["error"])
        sys.exit(1)
    all_pass = True
    for k, v in results.items():
        if k == "shadow":
            continue
        mark = "✅ PASS" if v["pass"] else "❌ FAIL"
        all_pass = all_pass and v["pass"]
        print(f"  {mark} {_label(k)}: {v['value']}")
    print(f"\n  總體: {'✅ 全部達標' if all_pass else '❌ 未達標 (需調整後重跑)'}")
    print("════════════════════════════════════════")
    return 0 if all_pass else 1


def _label(k: str) -> str:
    return {
        "short_ratio": "做空決策佔比 (Short Ratio)",
        "total_pnl": "總體淨盈虧 (PnL)",
        "max_drawdown": "最大回撤 (MDD)",
        "fallback_rate": "評分卡兜底率 (Fallback Rate)",
    }.get(k, k)


if __name__ == "__main__":
    sys.exit(main())
