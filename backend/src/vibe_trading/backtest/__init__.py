"""Minimal backtest compatibility package.

Submodules:
- engine: rule-based MA-crossover backtest (fast baseline, free)
- agent_replay / agent_isolation / agent_cache / agent_report / agent_models:
  agent-in-the-loop replay (full 13-agent LLM pipeline over historical bars)
"""
from .agent_models import AgentReplayConfig, AgentReplayResult, ReplayRecord
from .engine import BacktestEngine

__all__ = [
    "AgentReplayConfig",
    "AgentReplayResult",
    "ReplayRecord",
    "BacktestEngine",
]
