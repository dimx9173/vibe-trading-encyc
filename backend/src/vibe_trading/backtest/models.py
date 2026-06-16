"""Backtest configuration models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List


class LLMMode(str, Enum):
    """LLM usage mode for backtests."""
    SIMULATED = "simulated"
    LIVE = "live"


class ReportFormat(str, Enum):
    """Supported report output formats."""
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    symbol: str
    interval: str
    start_time: datetime
    end_time: datetime
    initial_balance: float = 10_000.0
    llm_mode: LLMMode = LLMMode.SIMULATED
    report_formats: List[ReportFormat] = field(default_factory=lambda: [ReportFormat.TEXT])
