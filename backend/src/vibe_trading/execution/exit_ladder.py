"""退出階梯 (Phase 4.2, 採納評估 A5).

trailing: 峰值漲幅 ≥5% 啟動, 峰值回撤 ≥3% 全出
moonbag: TP1 +10% 賣 50%, 剩 50% 繼續跑 trailing
純函式 + dataclass, 無副作用.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ExitState:
    symbol: str
    entry_price: float
    peak_price: float
    trailing_active: bool = False
    moonbag_sold: bool = False
    trailing_activate_pct: float = 0.05   # +5% 啟動
    trailing_exit_dd_pct: float = 0.03    # 峰值回撤 3% 全出
    moonbag_tp_pct: float = 0.10          # +10% 賣 50%


def make_exit_state(symbol: str, entry_price: float) -> ExitState:
    return ExitState(symbol=symbol, entry_price=entry_price, peak_price=entry_price)


def update_exit(
    state: ExitState,
    current_price: float,
    position_quantity: float,
) -> Dict[str, Any]:
    """更新退出狀態, 回傳動作.

    Returns: {"action": "hold"|"sell_all"|"sell_half", "reason": str, "quantity": float}
    """
    if position_quantity <= 0 or current_price <= 0:
        return {"action": "hold", "reason": "no position", "quantity": 0.0}

    state.peak_price = max(state.peak_price, current_price)
    gain = current_price / state.entry_price - 1.0

    # moonbag: +10% 賣 50% (觸發一次)
    if not state.moonbag_sold and gain >= state.moonbag_tp_pct:
        state.moonbag_sold = True
        state.trailing_active = True
        return {"action": "sell_half", "reason": f"moonbag TP +{state.moonbag_tp_pct:.0%}",
                "quantity": position_quantity * 0.5}

    # trailing: 峰值漲幅 ≥5% 啟動
    if not state.trailing_active:
        if gain >= state.trailing_activate_pct:
            state.trailing_active = True
        else:
            return {"action": "hold", "reason": "trailing not active", "quantity": 0.0}

    # trailing 回撤: 峰值回撤 ≥3% 全出
    drawdown = 1.0 - current_price / state.peak_price
    if drawdown >= state.trailing_exit_dd_pct:
        return {"action": "sell_all", "reason": f"trailing exit (dd {drawdown:.1%})",
                "quantity": position_quantity}
    return {"action": "hold", "reason": "trailing active", "quantity": 0.0}
