"""Grounding Gate — 交易計畫價格 vs OHLC 證據確定性校驗 (Roadmap Phase 1.2).

對齊 HKUDS/Vibe-Trading 的 Grounding 防幻覺閘門: LLM 產生的交易計畫
價格必須落在當前 bar 實測範圍附近, 否則判定違規。違規不 raise — 由
caller 降級決策 (HOLD) 並記錄。

設計決策 (plan grounding-gate-phase1.2):
- 校驗對象: TradingPlan 的結構化價格 (entry/stop_loss/take_profit),
  非 regex 掃描 rationale (既有 grounded_validation.py 是分析師層 legacy)
- fail-open: 無 OHLC 證據 (bar_low/high ≤ 0) 時 passed=True, 不臆斷
- stop/TP 用放寬倍率: 止損在 bar 外是正常保護, 避免誤殺
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 容差: 價格可偏離 bar [low, high] 的倍率
BAND_MULTIPLIER = 0.02
# 止損/止盈放寬倍率 (止損常設於 bar 外側)
BAND_MULTIPLIER_WIDE = 0.10


def _price_points(trading_plan: Any) -> List[Tuple[str, float]]:
    """從 TradingPlan 抽取所有價格點: (標籤, 價格)."""
    points: List[Tuple[str, float]] = []
    for i, order in enumerate(getattr(trading_plan, "entry_orders", None) or []):
        price = order.get("price")
        if price:
            points.append((f"entry_{i + 1}", float(price)))
    for i, sl in enumerate(getattr(trading_plan, "stop_loss_orders", None) or []):
        price = sl.get("trigger_price") or sl.get("price")
        if price:
            points.append((f"stop_loss_{i + 1}", float(price)))
    for i, tp in enumerate(getattr(trading_plan, "take_profit_orders", None) or []):
        price = tp.get("price")
        if price:
            points.append((f"take_profit_{i + 1}", float(price)))
    return points


def validate_trading_plan_prices(
    trading_plan: Any,
    bar_low: float,
    bar_high: float,
    current_price: float,
    band_multiplier: float = BAND_MULTIPLIER,
    band_multiplier_wide: float = BAND_MULTIPLIER_WIDE,
) -> Dict[str, Any]:
    """校驗計畫價格 vs 當前 bar [low, high] ± 容差.

    Args:
        trading_plan: TradingPlan 實例 (或具 entry_orders/stop_loss_orders/
                      take_profit_orders 屬性的物件)
        bar_low: 當前 bar 最低價
        bar_high: 當前 bar 最高價
        current_price: 當前價格 (保留供未來擴展)
        band_multiplier: entry 價格容差倍率 (預設 2%)
        band_multiplier_wide: stop/TP 價格容差倍率 (預設 10%)

    Returns:
        {"passed": bool, "violations": [...], "checked_points": N,
         "reason": str | None}
    """
    violations: List[str] = []

    # fail-open: 無 OHLC 證據不攔截
    if bar_low <= 0 or bar_high <= 0:
        return {
            "passed": True,
            "violations": [],
            "checked_points": 0,
            "reason": "no OHLC evidence available",
        }

    low_bound = bar_low * (1 - band_multiplier)
    high_bound = bar_high * (1 + band_multiplier)
    low_bound_wide = bar_low * (1 - band_multiplier_wide)
    high_bound_wide = bar_high * (1 + band_multiplier_wide)

    for label, price in _price_points(trading_plan):
        if label.startswith(("stop_loss", "take_profit")):
            # 止損/止盈常設於 bar 外側 — 放寬倍率
            lo, hi = low_bound_wide, high_bound_wide
        else:
            lo, hi = low_bound, high_bound
        if price < lo or price > hi:
            violations.append(
                f"{label} {price:.2f} 超出允許範圍 [{lo:.2f}, {hi:.2f}] "
                f"(bar {bar_low:.2f}~{bar_high:.2f})"
            )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "checked_points": len(_price_points(trading_plan)),
        "reason": None,
    }
