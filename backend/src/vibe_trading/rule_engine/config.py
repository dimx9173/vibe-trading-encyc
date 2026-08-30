"""Rule-engine configuration (spec phase1-rule-engine-regime-gate.md §3.4).

Values load from the environment with the ``RULE_`` prefix (same source
pattern as ``config/settings.py``), so stage-2 tuning only touches config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class RuleEngineConfig:
    """可调参数（阶段 2 回测不过时只改这里，不加新功能）."""

    entry_threshold: float = 0.3           # |composite| ≥ 阈值 → LONG/SHORT
    atr_period: int = 14                   # ATR 周期
    sl_atr_mult: float = 1.5               # 初始止损距离 = 1.5 × ATR (与 ExitLadderEngine 的 R 口径一致)
    tp_atr_mult: float = 2.5               # 初始止盈距离 = 2.5 × ATR
    neutral_risk_scale: float = 0.5        # NEUTRAL 半仓系数
    macro_max_age_seconds: int = 14400     # macro state 最大年龄 (4hr; macro 线程 2hr 一跑，容忍一次失敗)
    max_single_notional: float = 500.0     # 单笔名义价值上限 (5% of 10k)

    interval: str = "30m"                  # 规则回路 K 线周期 (multi_thread_main 设定覆盖，30m 主执行)
    macro_interval_seconds: int = 7200     # LLM 判斷週期 (2hr)
    macro_lookback_hours: int = 24         # 每次判斷回看的 K 線時長 (24hr @ 30m = 48根)

    bb_width_ratio: float = 0.7           # 自适应 BB 阈值系数：T_bb_adapt = median(bb_w[-20:]) * bb_width_ratio
    bb_width_floor: float = 0.015        # BB 阈值下限，防止极端低波动过度 FLAT
    rsi_neutral: float = 0.4             # RSI 中性阈值，用于迟滞判断
    choppy_enter_bars: int = 3           # 进入 CHOPPY 模态需持续低于阈值的 K 线根数
    choppy_exit_bars: int = 2            # 退出 CHOPPY 模态需持续高于阈值的 K 线根数
    mr_sl_atr: float = 2.5              # 均值回归模态止损 ATR 倍数
    mr_tp_atr: float = 1.8              # 均值回归模态止盈 ATR 倍数
    mr_trailing: float = 0.0             # 均值回归模态 trailing ATR 系数

    @classmethod
    def from_env(cls) -> "RuleEngineConfig":
        """从环境变量装载 (前缀 RULE_)."""
        return cls(
            entry_threshold=_env_float("RULE_ENTRY_THRESHOLD", cls.entry_threshold),
            atr_period=_env_int("RULE_ATR_PERIOD", cls.atr_period),
            sl_atr_mult=_env_float("RULE_SL_ATR_MULT", cls.sl_atr_mult),
            tp_atr_mult=_env_float("RULE_TP_ATR_MULT", cls.tp_atr_mult),
            neutral_risk_scale=_env_float("RULE_NEUTRAL_RISK_SCALE", cls.neutral_risk_scale),
            macro_max_age_seconds=_env_int("RULE_MACRO_MAX_AGE_SECONDS", cls.macro_max_age_seconds),
            max_single_notional=_env_float("RULE_MAX_SINGLE_NOTIONAL", cls.max_single_notional),
            interval=os.getenv("RULE_INTERVAL", cls.interval),
            macro_interval_seconds=_env_int("RULE_MACRO_INTERVAL_SECONDS", cls.macro_interval_seconds),
            macro_lookback_hours=_env_int("RULE_MACRO_LOOKBACK_HOURS", cls.macro_lookback_hours),
            bb_width_ratio=_env_float("RULE_BB_WIDTH_RATIO", cls.bb_width_ratio),
            bb_width_floor=_env_float("RULE_BB_WIDTH_FLOOR", cls.bb_width_floor),
            rsi_neutral=_env_float("RULE_RSI_NEUTRAL", cls.rsi_neutral),
            choppy_enter_bars=_env_int("RULE_CHOPPY_ENTER_BARS", cls.choppy_enter_bars),
            choppy_exit_bars=_env_int("RULE_CHOPPY_EXIT_BARS", cls.choppy_exit_bars),
            mr_sl_atr=_env_float("RULE_MR_SL_ATR", cls.mr_sl_atr),
            mr_tp_atr=_env_float("RULE_MR_TP_ATR", cls.mr_tp_atr),
            mr_trailing=_env_float("RULE_MR_TRAILING", cls.mr_trailing),
        )
