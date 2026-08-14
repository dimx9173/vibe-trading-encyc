# Agent replay and rule backtest are separate, layered backtests

The project has two backtest systems with different purposes: the rule-based `backtest/engine.py` (MA-crossover, seconds, free, does not exercise the agents) and agent replay (full 13-agent pipeline over historical bars, minutes per bar, paid LLM calls). They are intentionally separate and layered — rule backtest is the fast baseline and sanity check; agent replay is the authoritative validation of the agent system. Neither replaces the other, and the rule engine is not deprecated.

The alternative — removing the rule engine or merging both into one "backtest" — was rejected: the rule engine is a free, deterministic oracle that catches gross errors in data loading and execution math before spending LLM budget, and its results provide a reference distribution for the agent replay's decision histogram.

**Status**: accepted

**Considered Options**:
- Keep both, layered (chosen) — rule engine as free sanity check, agent replay as authoritative; CLI and reports must label which kind produced a result
- Remove rule engine — loses the free oracle; the user's "if no agent-in-the-loop it's useless" framing does not require deleting the rule engine, only that agent replay exists
- Merge into one engine — would couple LLM cost into every backtest run

**Consequences**:
- Two `backtest-*` CLI namespaces (rule engine is internal; `backtest-agent` is the CLI surface) — naming must stay distinct to avoid reader confusion
- Report formats must state the backtest kind explicitly
