"""Three-state regime gate + discrete CHOPPY/TRENDING/UNCERTAIN (spec §4).

Primary stays RISK_ON/NEUTRAL/RISK_OFF. Discrete detail only de-risks:
qty *= DISCRETE_QTY[detail], threshold *= DISCRETE_THR[detail] (Task 5).
Stale -> (NEUTRAL, UNCERTAIN). Missing detail -> UNCERTAIN.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pi_logger import get_logger

from vibe_trading.data_sources.macro_storage import MacroStorage

logger = get_logger(__name__)


class Regime(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


Detail = Literal["CHOPPY", "TRENDING", "UNCERTAIN"]

DISCRETE_QTY: dict[str, float] = {"CHOPPY": 0.3, "TRENDING": 1.0, "UNCERTAIN": 0.5}
DISCRETE_THR: dict[str, float] = {"CHOPPY": 1.4, "TRENDING": 1.0, "UNCERTAIN": 1.2}

_VALID_DETAIL = {"CHOPPY", "TRENDING", "UNCERTAIN"}

_TREND_STRENGTH_SCORE: dict = {"STRONG": 0.8, "MODERATE": 0.5, "WEAK": 0.2}


def _normalize_detail(value: Any) -> Detail:
    s = str(value or "").strip().upper()
    if s in _VALID_DETAIL:
        return s  # type: ignore[return-value]
    return "UNCERTAIN"


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
) -> Regime:
    """旧值 BULL/BEAR/NEUTRAL 与新三态 RISK_ON/NEUTRAL/RISK_OFF 统一映射.

    BULL → RISK_ON; BEAR 且 trend_strength ≥ 0.6 → RISK_OFF;
    其余（BEAR 弱趋势 / NEUTRAL / 未知 / 空）→ NEUTRAL。
    trend_strength 按 MacroState 实际型别存 STRONG/MODERATE/WEAK 字符串，
    由 _coerce_trend_strength 映射为 0.8/0.5/0.2。
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


async def current_regime_with_score(
    macro_storage: MacroStorage,
    max_age_seconds: int = 14400,
    symbol: str = "BTCUSDT",
) -> tuple[Regime, Detail]:
    """Discrete 3档: (Regime, detail) where detail in CHOPPY/TRENDING/UNCERTAIN."""
    try:
        state = await macro_storage.get_latest_state(None)
    except Exception as e:
        logger.warning(f"current_regime_with_score read failed ({symbol}): {e}", tag="RegimeGate")
        return Regime.NEUTRAL, "UNCERTAIN"
    if state is None:
        return Regime.NEUTRAL, "UNCERTAIN"
    if not _fresh(state, max_age_seconds):
        logger.info(f"macro state stale for {symbol} (age>={max_age_seconds}s) -> NEUTRAL/UNCERTAIN", tag="RegimeGate")
        return Regime.NEUTRAL, "UNCERTAIN"
    regime = map_macro_to_regime(getattr(state, "market_regime", ""), getattr(state, "trend_strength", ""))
    detail = _normalize_detail(getattr(state, "regime_detail", None))
    return regime, detail


async def current_regime(
    macro_storage: MacroStorage,
    max_age_seconds: int = 7200,
    symbol: str = "BTCUSDT",
) -> Regime:
    regime, _ = await current_regime_with_score(macro_storage, max_age_seconds=max_age_seconds, symbol=symbol)
    return regime