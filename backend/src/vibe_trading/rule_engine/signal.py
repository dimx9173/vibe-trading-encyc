"""Signal generation from AlphaZoo factors (spec phase1-rule-engine-regime-gate.md §3.1).

Pure functions — no storage / no side effects. All edge cases covered by
``tests/test_rule_engine_signal.py``.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Sequence

import numpy as np

MOMENTUM_KEYS: Sequence[str] = ("momentum_12_1", "rate_of_change")

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


def mean_reversion_score(rsi_zscore: float | None, price_to_ma: float | None) -> float:
    vals: List[float] = []
    if rsi_zscore is not None:
        try:
            vals.append(float(rsi_zscore))
        except Exception:
            pass
    if price_to_ma is not None:
        try:
            vals.append(float(price_to_ma) * 10)
        except Exception:
            pass
    if not vals:
        return 0.0
    return -momentum_tanh_score(vals)


def _bb_median(bb_history: Sequence[float]) -> float:
    tail = [float(v) for v in list(bb_history)[-20:] if v is not None]
    tail = [v for v in tail if np.isfinite(v)]
    if not tail:
        return 0.0
    return float(statistics.median(tail))


@dataclass
class RuleSignal:
    """因子 → 方向信号."""

    direction: Literal["LONG", "SHORT", "FLAT"]
    strength: float
    composite: float
    fake_breakout_warning: bool
    reason: str


def generate_signal(
    factors: Dict[str, float],
    threshold: Optional[float] = None,
    bb_history: Sequence[float] | None = None,
    mr_enabled: bool = False,
) -> RuleSignal:
    """从 AlphaZoo 因子字典生成规则信号（纯函数）.

    Args:
        factors: AlphaZoo.calculate 的输出 (≥50 根 bar)；可含可选
                 fake_breakout_warning（0/1）键。
        threshold: 入场阈值 (|composite|)；None → 0.3 (RuleEngineConfig.entry_threshold 默认).
        bb_history: 可选 BB 宽度历史序列，用于自适应迟滞判断。
        mr_enabled: 橫盤時是否啟用均值回歸分 (CHOPPY→FLAT 默认，True→使用 s_mr)。

    Returns:
        RuleSignal；因子不足（{}）或假突破 → FLAT。
    """
    if threshold is None:
        threshold = DEFAULT_ENTRY_THRESHOLD

    if not factors:
        return RuleSignal(
            direction="FLAT",
            strength=0.0,
            composite=0.0,
            fake_breakout_warning=False,
            reason="insufficient factors (<50 bars)",
        )

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
    s_mom = momentum_tanh_score(mom_vals) if mom_vals else 0.0
    rsi_z = factors.get("rsi_zscore")
    price_to_ma = factors.get("price_to_ma")
    s_mr = mean_reversion_score(
        float(rsi_z) if rsi_z is not None else None,
        float(price_to_ma) if price_to_ma is not None else None,
    )

    mode: str = "TRENDING"
    median_val: float | None = None
    t_adapt: float | None = None
    if bb_history is not None and len(bb_history) >= 1:
        try:
            from vibe_trading.rule_engine.config import RuleEngineConfig
        except Exception:
            RuleEngineConfig = None  # type: ignore
        if RuleEngineConfig is not None:
            cfg = RuleEngineConfig()
            median_val = _bb_median(bb_history)
            t_adapt = max(median_val * cfg.bb_width_ratio, cfg.bb_width_floor)
            t_exit = t_adapt * 1.3
            n_enter = cfg.choppy_enter_bars
            n_exit = cfg.choppy_exit_bars
            last_enter_end = -1
            last_exit_end = -1
            hist = [float(v) for v in bb_history if v is not None]
            for i in range(len(hist) - n_enter + 1):
                window = hist[i : i + n_enter]
                if all(v < t_adapt for v in window):
                    last_enter_end = i + n_enter - 1
            for i in range(len(hist) - n_exit + 1):
                window = hist[i : i + n_exit]
                if all(v > t_exit for v in window):
                    last_exit_end = i + n_exit - 1
            if last_enter_end != -1 or last_exit_end != -1:
                if last_enter_end > last_exit_end:
                    if rsi_z is None or abs(float(rsi_z)) < cfg.rsi_neutral:
                        mode = "CHOPPY"
                    else:
                        mode = "TRENDING"
                elif last_exit_end > last_enter_end:
                    mode = "TRENDING"
                else:
                    mode = "TRENDING"
            else:
                bb_w = factors.get("bollinger_band_width")
                if bb_w is not None and median_val is not None and t_adapt is not None:
                    try:
                        bb_w_f = float(bb_w)
                        rsi_ok = rsi_z is None or abs(float(rsi_z)) < cfg.rsi_neutral
                        if bb_w_f < t_adapt and rsi_ok:
                            mode = "CHOPPY"
                    except Exception:
                        pass

    if mode == "CHOPPY" and not mr_enabled:
        median_str = f"{median_val:.4f}" if median_val is not None else "n/a"
        t_str = f"{t_adapt:.4f}" if t_adapt is not None else "n/a"
        return RuleSignal(
            direction="FLAT",
            strength=0.0,
            composite=0.0,
            fake_breakout_warning=False,
            reason=f"choppy — FLAT (adaptive BB, median={median_str}, T={t_str})",
        )

    composite = s_mr if (mode == "CHOPPY" and mr_enabled) else s_mom

    if composite >= threshold:
        direction: Literal["LONG", "SHORT", "FLAT"] = "LONG"
        reason = f"composite {composite:+.3f} >= +{threshold}"
    elif composite <= -threshold:
        direction = "SHORT"
        reason = f"composite {composite:+.3f} <= -{threshold}"
    else:
        direction = "FLAT"
        reason = f"composite {composite:+.3f} within ±{threshold}"

    if mode == "CHOPPY" and mr_enabled:
        reason = f"[CHOPPY MR] {reason}"

    return RuleSignal(
        direction=direction,
        strength=abs(composite),
        composite=composite,
        fake_breakout_warning=False,
        reason=reason,
    )
