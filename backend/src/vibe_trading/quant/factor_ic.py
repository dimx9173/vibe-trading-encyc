"""
動態因子 IC 軟性調權引擎 (Harvested Alpha 模組五 — 規格書 §2.5)

對長度 N=50 的因子序列 F 與未來 3-bar 收益率 R 計算 Spearman Rank IC:
    Rank IC = 1 - (6 Σ d_i²) / (N(N²-1))

加權乘數映射 (平滑):
    IC > 0.15  → ×1.5
    0.05 ≤ IC ≤ 0.15 → ×1.0
    0.02 ≤ IC < 0.05 → 0.3 + 0.7*(IC-0.02)/0.03
    IC < 0.02  → ×0.3
    IC < -0.08 → 逆向警示 (負相關反向)
"""
from __future__ import annotations

from typing import Dict, List, Optional


def spearman_rank_ic(factor_values: List[float], forward_returns: List[float]) -> Optional[float]:
    """計算 Spearman Rank IC (兩序列秩相關係數).

    Args:
        factor_values: 因子值序列 (長度 N)
        forward_returns: 未來 3-bar 收益率序列 (長度 N)

    Returns:
        Rank IC [-1, 1] 或 None (資料不足/無變異)
    """
    if len(factor_values) != len(forward_returns) or len(factor_values) < 3:
        return None

    def _rank(seq: List[float]) -> List[float]:
        idx = sorted(range(len(seq)), key=lambda i: seq[i])
        ranks = [0.0] * len(seq)
        for pos, i in enumerate(idx):
            ranks[i] = pos + 1
        return ranks

    f_rank = _rank(factor_values)
    r_rank = _rank(forward_returns)
    n = len(factor_values)

    d2 = sum((f - r) ** 2 for f, r in zip(f_rank, r_rank))
    denom = n * (n * n - 1)
    if denom == 0:
        return None
    return 1.0 - 6.0 * d2 / denom


def ic_multiplier(rank_ic: float) -> Dict[str, object]:
    """依 Rank IC 映射加權乘數 (規格書 §2.5).

    Returns:
        {"multiplier": float, "signal": "STRONG_PREDICTIVE"|"NORMAL"|"WEAK"|
                                "NOISE"|"REVERSAL"}
    """
    if rank_ic > 0.15:
        return {"multiplier": 1.5, "signal": "STRONG_PREDICTIVE"}
    if rank_ic >= 0.05:
        return {"multiplier": 1.0, "signal": "NORMAL"}
    if rank_ic >= 0.02:
        m = 0.3 + 0.7 * (rank_ic - 0.02) / 0.03
        return {"multiplier": round(min(max(m, 0.3), 1.0), 4), "signal": "WEAK"}
    if rank_ic < -0.08:
        return {"multiplier": 0.3, "signal": "REVERSAL"}
    return {"multiplier": 0.3, "signal": "NOISE"}


def ema_smooth_multiplier(prev: float, new: float, alpha: float = 0.2) -> float:
    """IC 乘數 EMA 平滑過渡 (計劃書 §7: 防止相鄰 Bar 劇烈跳變)."""
    return round(prev + alpha * (new - prev), 4)


class DynamicICMonitor:
    """滾動 50-bar Rank IC 監控器 (每 10 bar 評估)."""

    def __init__(self, lookback: int = 50, forward: int = 3):
        self.lookback = lookback
        self.forward = forward
        self._factor_history: Dict[str, List[float]] = {}
        self._price_history: List[float] = []
        self._multipliers: Dict[str, float] = {}

    def update_price(self, price: float) -> None:
        self._price_history.append(price)

    def record_factor(self, factor_name: str, value: float) -> None:
        self._factor_history.setdefault(factor_name, []).append(value)

    def _forward_returns(self) -> List[float]:
        """未來 3-bar 收益率 (對齊窗口)."""
        prices = self._price_history
        n = len(prices)
        if n < self.lookback + self.forward:
            return []
        returns = []
        for i in range(n - self.lookback - self.forward, n - self.forward):
            p0 = prices[i]
            p1 = prices[i + self.forward]
            if p0 > 0:
                returns.append((p1 - p0) / p0)
            else:
                returns.append(0.0)
        return returns

    def evaluate(self) -> Dict[str, Dict[str, object]]:
        """評估所有因子 IC + 乘數 (平滑).

        Returns:
            {factor_name: {"rank_ic": float, "multiplier": float, "signal": str}}
        """
        fwd = self._forward_returns()
        if len(fwd) < 3:
            return {}
        results: Dict[str, Dict[str, object]] = {}
        for name, hist in self._factor_history.items():
            if len(hist) < self.lookback:
                continue
            factor_window = hist[-self.lookback:]
            ic = spearman_rank_ic(factor_window, fwd)
            if ic is None:
                continue
            mapped = ic_multiplier(ic)
            prev = self._multipliers.get(name, 1.0)
            mapped_mult = float(mapped["multiplier"]) if isinstance(mapped["multiplier"], (int, float)) else 1.0
            smooth = ema_smooth_multiplier(prev, mapped_mult)
            self._multipliers[name] = smooth
            results[name] = {
                "rank_ic": round(ic, 4),
                "multiplier": smooth,
                "signal": mapped["signal"],
            }
        return results

    def get_analyst_multipliers(self) -> Dict[str, float]:
        """返回給打分卡的平滑乘數表."""
        return dict(self._multipliers)
