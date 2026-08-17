"""
Deflated Sharpe Ratio (DSR) 顯著性檢驗 (Harvested Alpha 模組六 — 規格書 §2.6)

Bailey & López de Prado (2014):
    DSR = Φ( (SR - SR₀)·√(T-1) / √(1 - γ₃·SR + (γ₄-1)/4·SR²) )
    SR₀ = √(2·ln K) · ( (1-γ)·1/√(2·ln K) + γ )
其中 K = 歷史測試策略總數 (多重檢驗校正), γ = 歐拉-馬斯凱若尼常數 ≈ 0.5772.
判定: DSR ≥ 0.95 (p ≤ 0.05) → 真實顯著 Alpha.
"""
from __future__ import annotations

import math
from typing import Dict, List

_EULER_GAMMA = 0.5772156649015329  # γ


def _normal_cdf(x: float) -> float:
    """標準常態 CDF (Acklam 近似, 誤差 < 1e-4)."""
    sign = 1.0 if x >= 0 else -1.0
    z = abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                 - 0.284496736) * t + 0.254829592) * t * math.exp(-z * z)
    return 0.5 * (1.0 + sign * y)


def sharpe_ratio(returns: List[float], annualize: bool = False) -> float:
    """計算 Sharpe Ratio (均值/標準差)."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if var <= 1e-12:
        return 0.0
    sr = mean / math.sqrt(var)
    return sr * math.sqrt(252) if annualize else sr


def _skewness(returns: List[float]) -> float:
    n = len(returns)
    if n < 3:
        return 0.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m3 = sum((r - mean) ** 3 for r in returns) / n
    if m2 <= 1e-12:
        return 0.0
    return m3 / (m2 ** 1.5)


def _kurtosis(returns: List[float]) -> float:
    n = len(returns)
    if n < 4:
        return 0.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    if m2 <= 1e-12:
        return 0.0
    return m4 / (m2 ** 2) - 3.0  # 超額峰度


def expected_max_sharpe(num_trials: int, non_independent_trials: float = 1.0) -> float:
    """期望最大 Sharpe (多重檢驗校正): SR₀.

    Args:
        num_trials: K — 歷史測試策略總數
        non_independent_trials: γ — 非獨立試驗比例 (預設 1.0 保守)
    """
    if num_trials < 1:
        return 0.0
    ln_k = math.log(num_trials)
    if ln_k <= 0:
        return 0.0
    return math.sqrt(2.0 * ln_k) * (
        (1.0 - non_independent_trials) / math.sqrt(2.0 * ln_k)
        + non_independent_trials * _EULER_GAMMA
    )


def deflated_sharpe_ratio(
    returns: List[float],
    num_trials: int = 1,
    non_independent_trials: float = 1.0,
    annualized: bool = False,
) -> Dict[str, float]:
    """計算 DSR 與相關統計量.

    Returns:
        {"dsr": float, "sharpe": float, "sr0": float, "p_value": float,
         "significant": bool}
    """
    n = len(returns)
    if n < 3:
        return {"dsr": 0.0, "sharpe": 0.0, "sr0": 0.0, "p_value": 1.0,
                "significant": False}

    sr = sharpe_ratio(returns, annualize=annualized)
    sr0 = expected_max_sharpe(num_trials, non_independent_trials)
    gamma3 = _skewness(returns)
    gamma4 = _kurtosis(returns)

    denom = math.sqrt(max(1.0 - gamma3 * sr + (gamma4 - 1.0) / 4.0 * sr * sr, 1e-8))
    dsr_stat = (sr - sr0) * math.sqrt(n - 1) / denom
    dsr = _normal_cdf(dsr_stat)
    return {
        "dsr": round(dsr, 4),
        "sharpe": round(sr, 4),
        "sr0": round(sr0, 4),
        "p_value": round(1.0 - dsr, 4),
        "significant": bool(dsr >= 0.95),
    }
