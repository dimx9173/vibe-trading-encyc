"""Backtest configuration models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


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
    fee_rate: float = 0.001  # 0.1% trading fee
    slippage_rate: float = 0.0005  # 0.05% slippage


@dataclass
class Trade:
    """A single completed round-trip trade from the simulator."""
    entry_time: datetime
    exit_time: datetime
    side: str  # "LONG" or "SHORT"
    entry_price: float
    exit_price: float
    position_size: float
    pnl: float
    pnl_pct: float
    bars_held: int


@dataclass
class BacktestResult:
    """Aggregate statistics produced by BacktestEngine.run()."""
    symbol: str
    interval: str
    start_time: datetime
    end_time: datetime
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_pnl_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_pnl: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[Trade] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"Backtest {self.symbol} {self.interval}\n"
            f"  Total trades: {self.total_trades} (W:{self.winning_trades} / L:{self.losing_trades})\n"
            f"  Win rate: {self.win_rate:.1%}\n"
            f"  Total P&L: {self.total_pnl:.2f} USDT ({self.total_pnl_pct:.2%})\n"
            f"  Avg win: {self.avg_win:.2f}  Avg loss: {self.avg_loss:.2f}\n"
            f"  Max drawdown: {self.max_drawdown:.2f} USDT ({self.max_drawdown_pct:.2%})\n"
            f"  Sharpe: {self.sharpe_ratio:.2f}\n"
            f"  Final balance: {self.final_balance:.2f} USDT"
        )
