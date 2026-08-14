"""Agent-in-the-loop replay configuration and result models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentReplayConfig:
    """Configuration for an agent-in-the-loop replay run."""
    symbol: str = "BTCUSDT"
    interval: str = "30m"
    bars_path: str = "replay/data/bars.json"
    start: int = 120          # warmup bars skipped
    end: Optional[int] = None
    initial_balance: float = 10_000.0
    skip_debate: bool = False
    quiet: bool = False
    resume: bool = False      # skip bars already in log_path
    use_cache: bool = True    # LLM response cache on/off
    yes: bool = False         # skip cost-estimate confirmation
    db_path: str = "replay/data/replay_a.db"
    state_path: str = "replay/data/leg_a_state.json"
    log_path: str = "replay/data/leg_a_decisions.jsonl"
    usage_db_path: str = "vibe_trading.db"  # explicit; ledger default is CWD-relative
    cache_db_path: str = "replay/data/llm_cache.db"


@dataclass
class ReplayRecord:
    """One bar's decision and post-decision account state."""
    bar_open_ms: int
    bar_close: float
    decision: str
    confidence: Optional[float]
    elapsed_s: float
    balance: float
    equity: float
    positions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentReplayResult:
    """Aggregate statistics from an agent replay run."""
    symbol: str
    interval: str
    records: List[ReplayRecord] = field(default_factory=list)
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0
    decision_counts: Dict[str, int] = field(default_factory=dict)
    llm_cost_usd: float = 0.0
    llm_calls: int = 0

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Agent Replay {self.symbol} {self.interval}",
            f"  Bars: {len(self.records)}",
            f"  Total P&L: {self.total_pnl:.2f} USDT",
            f"  Realized: {self.realized_pnl:.2f}  Unrealized: {self.unrealized_pnl:.2f}",
            f"  Win rate (closed round-trips): {self.win_rate:.1%}",
            f"  Decisions: {self.decision_counts}",
            f"  LLM cost: ${self.llm_cost_usd:.4f} ({self.llm_calls} calls)",
        ]
        return "\n".join(lines)
