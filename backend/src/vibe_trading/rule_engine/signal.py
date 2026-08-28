"""Signal generation from AlphaZoo factors (spec phase1-rule-engine-regime-gate.md §3.1).

Pure functions — no storage / no side effects. All edge cases covered by
``tests/test_rule_engine_signal.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Sequence

import numpy as np

# 動量综合分使用的 AlphaZoo 因子子集 (对位 technical_tools.get_alpha_factor_summary
# 的 Momentum12_1 / RateOfChange / TrendStrength)。
MOMENTUM_KEYS: Sequence[str] = ("momentum_12_1", "rate_of_change", "trend_strength")

DEFAULT_ENTRY_THRESHOLD = 0.3


def momentum_tanh_score(values: Sequence[float]) -> float:
    """tanh 归一化动量综合分 [-1, 1]（复用 get_alpha_factor_summary 的逻辑，抽成可复用函数避免复制）。

    score = tanh(mean(values / max|values|))；无有效输入 → 0.0。
    """
    arr = np.asarray([float(v) for v in values if v is not None], dtype=float)
    if arr.size == 0:
        return 0.0
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.tanh(np.nanmean(arr / (np.abs(arr).max() + 1e-8))))


@dataclass
class RuleSignal:
    """因子 → 方向信号."""

    direction: Literal["LONG", "SHORT", "FLAT"]
    strength: float          # |composite|，供 sizing 参考
    composite: float         # tanh 归一化动量综合分 [-1, 1]
    fake_breakout_warning: bool
    reason: str              # 人读日志/TG 用


def generate_signal(
    factors: Dict[str, float],
    threshold: Optional[float] = None,
) -> RuleSignal:
    """从 AlphaZoo 因子字典生成规则信号（纯函数）.

    Args:
        factors: AlphaZoo.calculate 的输出 (≥50 根 bar)；可含可选
                 fake_breakout_warning（0/1）键。
        threshold: 入场阈值 (|composite|)；None → 0.3 (RuleEngineConfig.entry_threshold 默认).

    Returns:
        RuleSignal；因子不足（{}）或假突破 → FLAT。
    """
    if threshold is None:
        threshold = DEFAULT_ENTRY_THRESHOLD

    # 因子不足（<50 根 bar）→ FLAT
    if not factors:
        return RuleSignal(
            direction="FLAT",
            strength=0.0,
            composite=0.0,
            fake_breakout_warning=False,
            reason="insufficient factors (<50 bars)",
        )

    # 假突破过滤：fake_breakout_warning=True/1 → 降级 FLAT
    if bool(factors.get("fake_breakout_warning", 0.0)):
        return RuleSignal(
            direction="FLAT",
            strength=0.0,
            composite=0.0,
            fake_breakout_warning=True,
            reason="fake breakout warning",
        )

    mom_vals: List[float] = [
        factors[k] for k in MOMENTUM_KEYS if k in factors and factors[k] is not None
    ]
    composite = momentum_tanh_score(mom_vals) if mom_vals else 0.0

    if composite >= threshold:
        direction: Literal["LONG", "SHORT", "FLAT"] = "LONG"
        reason = f"composite {composite:+.3f} >= +{threshold}"
    elif composite <= -threshold:
        direction = "SHORT"
        reason = f"composite {composite:+.3f} <= -{threshold}"
    else:
        direction = "FLAT"
        reason = f"composite {composite:+.3f} within ±{threshold}"

    return RuleSignal(
        direction=direction,
        strength=abs(composite),
        composite=composite,
        fake_breakout_warning=False,
        reason=reason,
    )