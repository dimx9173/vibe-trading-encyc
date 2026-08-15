"""確定性風險計量: VaR/CVaR (Cornish-Fisher), EVT/GPD, GARCH(1,1), EWMA.

Roadmap Phase 1.1 — 對齊 HKUDS `src/quantlib` 設計: 金融數學與 LLM 嚴格解耦,
Agent 必須透過 Tool 取得確定性數值。純 NumPy + 標準庫, 零 scipy 依賴。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# Cornish-Fisher 修正分位數 z 值 (標準常態)
_Z_95 = 1.6448536269514722
_Z_99 = 2.3263478740408408

# GARCH(1,1) 預設參數 (v1 固定, v2 MLE)
GARCH_ALPHA = 0.05
GARCH_BETA = 0.90


@dataclass
class VaREstimate:
    """VaR/CVaR 計算結果."""
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    volatility: float
    method: str
    tail_shape: Optional[float] = None  # GPD shape ξ (EVT only)


def _norm_ppf(p: float) -> float:
    """標準常態分位數 (Acklam 有理近似 + Newton 修正, 誤差 ~1e-9, 無 scipy)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:  # 下尾
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p > phigh:  # 上尾
        q = math.sqrt(-2 * math.log(1-p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    else:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    # 一次 Newton 修正
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def _cornish_fisher_z(p: float, skew: float, excess_kurt: float) -> float:
    """Cornish-Fisher 修正分位數: 納入偏度與超額峰度的肥尾修正."""
    z = _norm_ppf(p)
    # CF 展開: z_cf = z + (z²−1)·S/6 + (z³−3z)·K/24 − (2z³−5z)·S²/36
    return z + (z * z - 1) * skew / 6.0 + (z**3 - 3 * z) * excess_kurt / 24.0 - (2 * z**3 - 5 * z) * skew * skew / 36.0


def _cvar_from_returns(returns: np.ndarray, threshold: float, position_value: float) -> float:
    """CVaR (expected shortfall): 低於分位數的條件平均損失."""
    tail = returns[returns <= threshold]
    if len(tail) == 0:
        return abs(threshold * position_value)
    return abs(np.mean(tail) * position_value)


def _evt_var(returns: np.ndarray, position_value: float, confidence: float) -> Optional[Tuple[float, float]]:
    """EVT Peaks-Over-Threshold / GPD 尾部 VaR.

    VaR_α = u + (β/ξ)·[(n·(1−α)/N_u)^(−ξ) − 1]
    Returns: (VaR_pct, GPD shape ξ) or None (樣本不足).
    """
    n = len(returns)
    # 閾值: 90 分位 (負收益率側, 取下尾)
    u = float(np.percentile(returns, 10))
    excess = returns[returns < u] - u
    nu = len(excess)
    if nu < 20:
        return None  # 樣本不足, 回退

    # GPD 參數 MLE (簡化: Pickands 估計器, 穩健且無迭代)
    excess_sorted = np.sort(excess)
    k = max(1, nu // 4)
    # Pickands: ξ = ln((x_{n-k} - x_{n-2k}) / (x_{n-2k} - x_{n-4k})) / ln(2)
    if nu >= 4 * k:
        x1 = excess_sorted[-k]
        x2 = excess_sorted[-2 * k]
        x4 = excess_sorted[-4 * k]
        denom = x2 - x4
        if denom > 0:
            xi = math.log((x1 - x2) / denom) / math.log(2)
            beta = xi * (x2 - x4) / (2**xi - 1) if abs(xi) > 1e-12 else (x1 - x4) / 2.0
        else:
            xi, beta = 0.0, float(np.mean(excess))
    else:
        xi, beta = 0.0, float(np.mean(excess))

    if abs(xi) < 1e-12:
        var_pct = u - beta * math.log(n * (1 - confidence) / nu)
    else:
        var_pct = u + (beta / xi) * ((n * (1 - confidence) / nu) ** (-xi) - 1)
    return var_pct, xi


def calculate_var(
    returns: np.ndarray,
    position_value: float,
    method: str = "cornish_fisher",
    confidence: float = 0.95,
) -> VaREstimate:
    """計算 VaR/CVaR.

    Args:
        returns: 收益率序列 (np.ndarray)
        position_value: 倉位價值
        method: historical / parametric / cornish_fisher / evt
        confidence: 信心水準 (0.95 或 0.99)

    Returns:
        VaREstimate (var_95/var_99/cvar_95/cvar_99 皆為正數損失金額)
    """
    returns = np.asarray(returns, dtype=float)

    # 樣本不足回退 (與 advanced_risk_tools 行為一致)
    if len(returns) < 10:
        return VaREstimate(
            var_95=position_value * 0.02,
            var_99=position_value * 0.03,
            cvar_95=position_value * 0.025,
            cvar_99=position_value * 0.04,
            volatility=0.02,
            method=method,
        )

    vol = float(np.std(returns))

    # EVT: 尾部估計 (95% 用 95 分位, 99% 用 99 分位)
    if method == "evt":
        evt = _evt_var(returns, position_value, confidence)
        if evt is not None:
            var_pct, xi = evt
            if confidence >= 0.99:
                var_99 = abs(var_pct * position_value)
                var_95 = abs(float(np.percentile(returns, 5)) * position_value)
            else:
                var_95 = abs(var_pct * position_value)
                var_99 = abs(float(np.percentile(returns, 1)) * position_value)
            return VaREstimate(
                var_95=var_95,
                var_99=var_99,
                cvar_95=abs(float(np.mean(returns[returns <= np.percentile(returns, 5)])) * position_value),
                cvar_99=abs(float(np.mean(returns[returns <= np.percentile(returns, 1)])) * position_value),
                volatility=vol,
                method="evt",
                tail_shape=xi,
            )
        # 樣本不足回退到 cornish_fisher
        method = "cornish_fisher"

    if method == "historical":
        var_95_pct = float(np.percentile(returns, 5))
        var_99_pct = float(np.percentile(returns, 1))
        var_95, var_99 = abs(var_95_pct * position_value), abs(var_99_pct * position_value)
        cvar_95 = _cvar_from_returns(returns, var_95_pct, position_value)
        cvar_99 = _cvar_from_returns(returns, var_99_pct, position_value)
        return VaREstimate(var_95, var_99, cvar_95, cvar_99, vol, method)

    # parametric / cornish_fisher
    mean = float(np.mean(returns))
    std = float(np.std(returns))
    if method == "parametric":
        z_95, z_99 = _Z_95, _Z_99
    else:  # cornish_fisher (預設)
        # 偏度與超額峰度 (樣本矩, 無偏修正)
        m2 = float(np.mean((returns - mean) ** 2))
        m3 = float(np.mean((returns - mean) ** 3))
        m4 = float(np.mean((returns - mean) ** 4))
        skew = m3 / (m2 ** 1.5) if m2 > 0 else 0.0
        excess_kurt = (m4 / (m2 ** 2) - 3.0) if m2 > 0 else 0.0
        z_95 = _cornish_fisher_z(0.05, skew, excess_kurt)
        z_99 = _cornish_fisher_z(0.01, skew, excess_kurt)

    var_95_pct = mean + z_95 * std
    var_99_pct = mean + z_99 * std
    var_95, var_99 = abs(var_95_pct * position_value), abs(var_99_pct * position_value)
    # CVaR (正態尾部期望)
    cvar_95 = abs((mean - std * _norm_pdf(z_95) / 0.05) * position_value)
    cvar_99 = abs((mean - std * _norm_pdf(z_99) / 0.01) * position_value)
    return VaREstimate(var_95, var_99, cvar_95, cvar_99, vol, method)


def _norm_pdf(x: float) -> float:
    """標準常態 PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


# ---------------------------------------------------------------------------
# GARCH(1,1) / EWMA 動態條件波動率
# ---------------------------------------------------------------------------

def ewma_volatility(returns: np.ndarray, lambda_: float = 0.94) -> float:
    """RiskMetrics EWMA: σ²ₜ = λ·σ²ₜ₋₁ + (1−λ)·r²ₜ₋₁ (初始 = 樣本變異數)."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.02
    var_prev = float(np.var(returns))
    for r in returns[1:]:
        var_prev = lambda_ * var_prev + (1 - lambda_) * (r * r)
    return float(math.sqrt(var_prev))


def garch11_volatility(
    returns: np.ndarray,
    omega: Optional[float] = None,
    alpha: float = GARCH_ALPHA,
    beta: float = GARCH_BETA,
) -> Tuple[float, np.ndarray]:
    """GARCH(1,1) 條件波動率序列.

    σ²ₜ = ω + α·r²ₜ₋₁ + β·σ²ₜ₋₁
    variance targeting: ω = (1−α−β)·Var(r) 確保收斂至長期變異數.

    Returns: (最終波動率, 全序列 σ²).
    """
    returns = np.asarray(returns, dtype=float)
    n = len(returns)
    if n < 2:
        return 0.02, np.array([0.0004])

    if omega is None:
        omega = (1 - alpha - beta) * float(np.var(returns))

    var_series = np.empty(n)
    var_series[0] = float(np.var(returns))
    for t in range(1, n):
        var_series[t] = omega + alpha * (returns[t - 1] ** 2) + beta * var_series[t - 1]

    return float(math.sqrt(var_series[-1])), var_series
