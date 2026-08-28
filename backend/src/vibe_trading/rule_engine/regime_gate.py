"""Three-state regime gate (spec phase1-rule-engine-regime-gate.md §3.2).

``RISK_OFF`` blocks new entries only — exits always proceed. Missing/stale
macro state fails safe to ``NEUTRAL`` (never ``RISK_ON``).
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pi_logger import get_logger

from vibe_trading.data_sources.macro_storage import MacroStorage

logger = get_logger(__name__)


class Regime(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


_TREND_STRENGTH_SCORE: dict = {"STRONG": 0.8, "MODERATE": 0.5, "WEAK": 0.2}


def _coerce_trend_strength(value: Any) -> float:
    """MacroState.trend_strength 存的是 STRONG/MODERATE/WEAK (字符串) → float."""
    if isinstance(value, bool):
        return 0.5
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper()
    return _TREND_STRENGTH_SCORE.get(s, 0.5)


def map_macro_to_regime(
    market_regime: str,
    trend_strength: Any,
    sentiment: str,
) -> Regime:
    """旧值 BULL/BEAR/NEUTRAL 与新三态 RISK_ON/NEUTRAL/RISK_OFF 统一映射.

    BULL → RISK_ON; BEAR 且 trend_strength ≥ 0.6 → RISK_OFF;
    其余（BEAR 弱趋势 / NEUTRAL / 未知 / 空）→ NEUTRAL。
    """
    regime = (market_regime or "").strip().upper()
    if regime in ("RISK_ON", "BULL"):
        return Regime.RISK_ON
    if regime == "BEAR":
        if _coerce_trend_strength(trend_strength) >= 0.6:
            return Regime.RISK_OFF
        return Regime.NEUTRAL
    if regime in ("RISK_OFF", "NEUTRAL"):
        return Regime(regime)
    return Regime.NEUTRAL


def _fresh(state: Any, max_age_seconds: int) -> bool:
    timestamp = int(getattr(state, "timestamp", 0) or 0)
    now_ms = int(time.time() * 1000)
    return now_ms - timestamp <= max_age_seconds * 1000


async def current_regime(
    macro_storage: MacroStorage,
    max_age_seconds: int = 7200,
    symbol: str = "BTCUSDT",
) -> Regime:
    """读取 macro state 判三态；无 state / 过期 / 读失败 → NEUTRAL (fail-safe)."""
    try:
        state = await macro_storage.get_latest_state(symbol)
    except Exception as e:
        logger.warning(f"current_regime read failed ({symbol}): {e}", tag="RegimeGate")
        return Regime.NEUTRAL
    if state is None:
        return Regime.NEUTRAL
    if not _fresh(state, max_age_seconds):
        logger.info(
            f"macro state stale for {symbol} "
            f"(age>={max_age_seconds}s) → NEUTRAL", tag="RegimeGate"
        )
        return Regime.NEUTRAL
    return map_macro_to_regime(
        getattr(state, "market_regime", ""),
        getattr(state, "trend_strength", ""),
        getattr(state, "overall_sentiment", ""),
    )