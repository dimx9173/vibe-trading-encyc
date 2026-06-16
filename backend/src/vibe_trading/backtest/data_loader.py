"""Backtest data loading facade."""
from __future__ import annotations

from enum import Enum


class DataSource(str, Enum):
    """Supported backtest data sources."""
    BINANCE = "binance"
    LOCAL = "local"
    HYBRID = "hybrid"


class BacktestDataLoader:
    """Minimal data loader shell used by current tests."""

    def __init__(self, default_source: DataSource = DataSource.HYBRID) -> None:
        self.default_source = default_source
