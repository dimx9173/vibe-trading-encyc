"""確定性執行計量: L2 盤口衝擊成本模型.

Roadmap Phase 1.1 — 純函式, 無 I/O, 零依賴.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 深度不足時的滑點上限標記 (bps)
MAX_SLIPPAGE_BPS = 100.0


def estimate_impact_cost(
    levels: List[Tuple[float, float]],
    order_qty: float,
    current_price: float,
) -> Dict[str, Any]:
    """L2 盤口衝擊: 依序吃單, 計算平均成交價與滑點成本.

    Args:
        levels: [(price, qty), ...] 按價位排序 (買單側: 由高到低)
        order_qty: 訂單數量 (正數)
        current_price: 當前 mid 價

    Returns:
        {"avg_fill_price": float, "slippage_bps": float,
         "filled_qty": float, "remaining_qty": float, "insufficient_depth": bool}
    """
    if order_qty <= 0 or current_price <= 0:
        return {
            "avg_fill_price": current_price,
            "slippage_bps": 0.0,
            "filled_qty": 0.0,
            "remaining_qty": order_qty,
            "insufficient_depth": False,
        }

    remaining = order_qty
    total_cost = 0.0
    total_qty = 0.0

    for price, qty in levels:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        total_cost += take * price
        total_qty += take
        remaining -= take

    insufficient = remaining > 1e-12

    if total_qty <= 0:
        # 無盤口可成交
        return {
            "avg_fill_price": current_price,
            "slippage_bps": MAX_SLIPPAGE_BPS,
            "filled_qty": 0.0,
            "remaining_qty": order_qty,
            "insufficient_depth": True,
        }

    avg_fill = total_cost / total_qty
    slippage_bps = abs(avg_fill - current_price) / current_price * 10000.0 if current_price else 0.0

    return {
        "avg_fill_price": avg_fill,
        "slippage_bps": slippage_bps,
        "filled_qty": total_qty,
        "remaining_qty": remaining,
        "insufficient_depth": insufficient,
    }


def estimated_slippage_bps(order_qty: float, depth_notional: float) -> float:
    """簡化滑點模型: 依訂單規模佔深度比例飽和.

    slippage_bps ≈ 10000 × (order_qty / (depth_notional + order_qty)), 上限 MAX_SLIPPAGE_BPS.
    """
    if order_qty <= 0 or depth_notional <= 0:
        return 0.0
    ratio = order_qty / (depth_notional + order_qty)
    return min(ratio * 10000.0, MAX_SLIPPAGE_BPS)
