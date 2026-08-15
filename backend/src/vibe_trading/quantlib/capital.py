"""確定性資金管理計量: Fractional Kelly, 最大回撤限制, TWR/XIRR.

Roadmap Phase 1.1 — 純函式, 無 I/O, 零依賴 (NumPy + 標準庫).
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


def fractional_kelly(win_rate: float, payoff_ratio: float, fraction: float = 0.5) -> float:
    """Fractional (半) 凱利公式.

    f* = fraction * (p − q/b)
    p = 勝率, q = 1−p, b = payoff ratio (平均盈利/平均虧損).

    Returns: 建議倉位比例 (0~1). 邊界: 負值 → 0 (不投注).
    """
    p = float(win_rate)
    b = float(payoff_ratio)
    q = 1.0 - p
    if b <= 0 or p <= 0 or p >= 1:
        return 0.0
    f = p - q / b
    return max(0.0, min(fraction * f, 1.0))


def max_drawdown_limit(
    position_fraction: float,
    max_dd_pct: float,
    current_dd_pct: float,
) -> float:
    """回撤縮倉: 當前回撤超過閾值時線性縮小倉位.

    current_dd ≤ 0 → 原倉位; current_dd ≥ max_dd → 0 (暫停交易);
    中間線性縮減.

    Returns: 調整後倉位比例 (0 ~ position_fraction).
    """
    pos = float(position_fraction)
    threshold = float(max_dd_pct)
    dd = float(current_dd_pct)
    if threshold <= 0:
        return pos
    if dd <= 0:
        return pos
    if dd >= threshold:
        return 0.0
    return pos * (1.0 - dd / threshold)


def twr(period_returns: np.ndarray) -> float:
    """時間加權回報 (Time-Weighted Return): Π(1+rᵢ) − 1."""
    returns = np.asarray(period_returns, dtype=float)
    if len(returns) == 0:
        return 0.0
    return float(np.prod(1.0 + returns) - 1.0)


def xirr(cashflows: List[Tuple[float, float]], max_iter: int = 50, tol: float = 1e-6) -> float:
    """不規則現金流內部報酬率 (XIRR) — 二分法求 NPV=0.

    cashflows: [(時間(年), 金額)] — 負為流出, 正為流入.
    時間基準: 最早時間視為 0 (內部自動歸零).

    Returns: 年化 IRR (小數). 不收斂時回傳 None 標記為 0.0 並由 caller 判斷.
    """
    if len(cashflows) < 2:
        return 0.0

    # 歸零時間基準
    t0 = min(t for t, _ in cashflows)
    flows = [(t - t0, amt) for t, amt in cashflows]

    def npv(rate: float) -> float:
        return sum(amt / (1.0 + rate) ** t for t, amt in flows)

    # 初值: 資金加權近似 (避免除零)
    total_out = -sum(amt for _, amt in flows if amt < 0)
    total_in = sum(amt for _, amt in flows if amt > 0)
    if total_out <= 0 or total_in <= 0:
        return 0.0

    # 二分法: NPV 在 rate → −1 時發散, 用 [−0.999, 10] 初始區間
    lo, hi = -0.999, 10.0
    f_lo = npv(lo)
    f_hi = npv(hi)
    if f_lo * f_hi > 0:
        # 同號: 嘗試展寬上界 (IRR 可能很高)
        for _ in range(40):
            hi *= 2
            if npv(hi) * f_lo <= 0:
                break
        if npv(lo) * npv(hi) > 0:
            return 0.0  # 無法收斂

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid

    return (lo + hi) / 2.0
