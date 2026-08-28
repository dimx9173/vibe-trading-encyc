"""Rule-engine configuration (spec phase1-rule-engine-regime-gate.md §3.4).

Values load from the environment with the ``RULE_`` prefix (same source
pattern as ``config/settings.py``), so stage-2 tuning only touches config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


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


_DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@dataclass
class RuleEngineConfig:
    """可调参数（阶段 2 回测不过时只改这里，不加新功能）."""

    entry_threshold: float = 0.3           # |composite| ≥ 阈值 → LONG/SHORT
    atr_period: int = 14                   # ATR 周期
    sl_atr_mult: float = 1.5               # 初始止损距离 = 1.5 × ATR (与 ExitLadderEngine 的 R 口径一致)
    tp_atr_mult: float = 2.5               # 初始止盈距离 = 2.5 × ATR
    neutral_risk_scale: float = 0.5        # NEUTRAL 半仓系数
    macro_max_age_seconds: int = 7200      # macro state 最大年龄 (2h; macro 线程 1h 一跑)
    max_single_notional: float = 500.0     # 单笔名义价值上限 (5% of 10k)

    interval: str = "30m"                  # 规则回路 K 线周期
    symbols: List[str] = field(default_factory=lambda: list(_DEFAULT_SYMBOLS))

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
            symbols=[s.strip() for s in os.getenv("RULE_SYMBOLS", ",".join(_DEFAULT_SYMBOLS)).split(",") if s.strip()],
        )
