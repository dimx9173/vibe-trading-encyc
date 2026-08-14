# Replay tool isolation uses monkey-patching, not storage injection

Agent replay (bar-by-bar replay of historical K-lines through the 13-agent decision pipeline) must block look-ahead: agents' tools must never read today's live market data. We implement this by monkey-patching module-level functions in `market_data_tools` / `fundamental_tools` / `sentiment_tools` / `technical_tools` to either read from replay storage or return "N/A", installed before coordinator construction.

The alternative — refactoring all 24 agent tools and `TradingCoordinator._get_analyst_data` to accept storage injection — was rejected: it touches the live trading path (risk of breaking production) for a concern that only exists in replay. The patch approach works because the coordinator imports tool functions inside function bodies (call-time binding), so patched module attributes are picked up.

**Status**: accepted

**Considered Options**:
- Monkey-patch module attributes (chosen) — no live-path changes, but requires coverage discipline; gaps silently leak live data (audit found 3: `ft.get_funding_rates` plural, `ft.get_open_interest` wrong namespace, `ft.get_fear_and_greed_index`)
- Storage injection refactor — clean, but touches 24 tools + coordinator across the live path

**Consequences**:
- Every new live-data tool added to the codebase must be added to `agent_isolation.py`'s patch list, or replay silently leaks today's data. Coverage is enforced by audit, not by the type system.
- Replay decisions see "N/A" for fundamental/sentiment inputs (funding, news, fear&greed) — a documented fidelity limitation, accepted for v1.
