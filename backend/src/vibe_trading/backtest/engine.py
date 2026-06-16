"""Backtest engine facade."""
from __future__ import annotations

from vibe_trading.backtest.models import BacktestConfig


class BacktestEngine:
    """Minimal backtest engine shell."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
