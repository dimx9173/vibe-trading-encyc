# Vibe Trading (VBT)

AI-driven quantitative trading system whose core value is a 13-agent LLM decision pipeline (agent-in-the-loop). The system makes trading decisions by having a team of LLM agents analyze market data, debate, assess risk, and decide — rather than executing fixed rules.

## Language

**Agent replay**:
Running the full agent decision pipeline bar-by-bar over historical K-lines to produce a decision and account-state sequence, with point-in-time integrity (no look-ahead).
_Avoid_: backtest (reserved for the rule-based engine), simulation

**Rule backtest**:
The fast, rule-based MA-crossover backtest engine (`backtest/engine.py`). Runs in seconds and costs nothing, but does not exercise the agents.
_Avoid_: backtest (when meaning agent replay)

**Decision cycle**:
One full pass of the 13-agent pipeline for one bar: analysts → research debate → risk assessment → trader plan → portfolio-manager final decision.
_Avoid_: round, iteration

**Bar**:
One historical K-line (open_time_ms, OHLCV) replayed through the pipeline. The replay is bar-driven: each bar is stored into isolated storage *before* the decision so the pipeline sees history only up to that bar.
_Avoid_: candle, kline (when meaning the replay unit)

**Warmup bars**:
Bars loaded before the replay window so indicators (SMA/RSI/MACD) have history to compute from. Not replayed, not scored.
_Avoid_: buffer, pre-roll

**Look-ahead**:
Any leak of data that would not have been knowable at the bar's decision time into that decision — e.g. today's funding rate injected into a historical decision. The replay harness blocks look-ahead by tool isolation (live-data tools return "N/A") and store-before-decide ordering.
_Avoid_: future data, point-in-time violation (keep the term look-ahead)

**Tool isolation**:
The monkey-patch layer that redirects agent tools from live APIs to replay storage (or "N/A") during an agent replay.
_Avoid_: sandbox, mock

**LLM cache**:
Persistent store of agent LLM responses keyed by (model, role, prompt_hash), so re-running a replay with unchanged prompts costs nearly nothing.
_Avoid_: prompt cache (ambiguous with provider-side caching)

**Round-trip**:
A completed long position: entry bar to exit bar. Win rate counts only completed round-trips, not per-bar equity changes.
_Avoid_: trade (when meaning the completed entry-exit pair)

**Paper executor**:
The simulated order executor used in replay; fills against bar closes fed per-bar by the replay driver, never live prices.
_Avoid_: mock executor, fake broker

**Replay driver**:
The program that fetches historical bars, seeds warmup into isolated storage, installs tool isolation, and drives `analyze_and_decide` bar-by-bar.
_Avoid_: runner, harness (keep driver)
