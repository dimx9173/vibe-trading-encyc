"""Lightweight LLM simulation utilities for backtest compatibility."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from vibe_trading.backtest.models import LLMMode
from vibe_trading.coordinator.signal_processor import TradingSignal


@dataclass
class HistoricalDecision:
    price: float
    indicators: Dict[str, Any]
    signal: TradingSignal
    confidence: float
    market_condition: str


class LLMSimulator:
    """Simple nearest-history simulator used by legacy tests."""

    def __init__(self) -> None:
        self.decisions: List[HistoricalDecision] = []

    def add_decision(
        self,
        *,
        price: float,
        indicators: Dict[str, Any],
        signal: TradingSignal,
        confidence: float,
        market_condition: str,
    ) -> None:
        self.decisions.append(HistoricalDecision(price, indicators, signal, confidence, market_condition))

    def simulate_decision(
        self,
        *,
        current_price: float,
        current_indicators: Dict[str, Any],
        current_positions: List[Any],
    ) -> Tuple[TradingSignal, float]:
        if not self.decisions:
            return TradingSignal.HOLD, 0.5
        latest = self.decisions[-1]
        return latest.signal, max(0.0, min(1.0, latest.confidence))


class LLMOptimizer:
    """Backtest LLM optimizer facade."""

    def __init__(self, mode: LLMMode = LLMMode.SIMULATED) -> None:
        self.mode = mode
        self.simulator = LLMSimulator()
