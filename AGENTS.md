# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Vibe Trading is a multi-agent cryptocurrency trading system powered by Large Language Models (LLMs). The system uses a collaborative agent architecture with 12 specialized agents working across 4 phases to make trading decisions.

**Core Architecture:**
- **pi_agent_core**: Agent framework with dual-loop message processing engine
- **pi_ai**: LLM abstraction layer supporting multiple providers (OpenAI, Anthropic, Google, custom endpoints)
- **pi_logger**: Structured logging system with colorized console output and file logging
- **vibe_trading**: Main trading application with agents, coordinators, data sources, and execution

**Decision Flow (4 Phases):**
1. **Phase 1 - Analysts**: Technical, Fundamental, News, Sentiment analysts (parallel execution)
2. **Phase 2 - Researchers**: Bull/Bear researchers debate → Research manager makes investment recommendation
3. **Phase 3 - Risk Team**: Aggressive, Neutral, Conservative risk assessments
4. **Phase 4 - Decision Layer**: Trader creates execution plan → Portfolio manager makes final decision

**Threading Architecture:**
- **Macro Thread**: Runs every hour, analyzes macro environment (trend, sentiment, events)
- **On Bar Thread**: K-line triggered, reads macro state and runs simplified 3-phase flow
- **Event Thread**: Real-time trigger monitoring with priority queue for emergency responses

## Development Commands

```bash
# Install dependencies
cd backend && uv pip install -e .

# Run trading system (multi-threaded)
PYTHONPATH=src uv run -- vibe-trade start BTCUSDT

# Run single analysis
PYTHONPATH=src uv run -- vibe-trade analyze --symbol BTCUSDT

# Run with web monitoring
uv run test_historical.py  # Web UI at http://localhost:8000

# Run specific tests
uv run test_technical_analysis.py
uv run test_sentiment_tools.py
uv run test_researchers.py

# Linting (use ruff, not black)
uv run ruff check backend/src/
uv run ruff format backend/src/

# Type checking
uv run mypy backend/src/
```

## Configuration

**Environment Variables (.env):**
- `LLM_MODEL`: Model name from `llm.yaml` (default: `glm_4_7`)
- `TRADING_MODE`: `paper` or `live`
- `BINANCE_TESTNET_API_KEY`/`BINANCE_TESTNET_API_SECRET`: For paper trading
- `BINANCE_API_KEY`/`BINANCE_API_SECRET`: For live trading
- `DATABASE_URL`: SQLite database path
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR

**LLM Configuration (backend/src/vibe_trading/config/llm.yaml):**
- Contains multiple model configurations (glm_4_7, iflow, longcat, etc.)
- `use_llm`: Default model to use
- Loaded via `vibe_trading/config/llm_config.py` (`get_model_from_config`); api_key injected via `AgentOptions(get_api_key=...)`.
- (Note: pi-py removed the `ModelRouter` / `model_router` / `agent_model_mapping` features; model selection is now by explicit `Model` instance.)

**Agent Configuration (backend/src/vibe_trading/config/agent_config.py):**
- `AgentRole`: Enum of all 12 agent roles
- `AgentConfig`: Per-agent configuration (temperature, model override, enabled status)
- `AgentTeamConfig`: Default configurations for all agents

## Key Architecture Patterns

### Agent System
- All agents inherit from `pi_agent_core.Agent` and use `agent_loop()` for execution
- Agents are created via `agent_factory.create_trading_agent()` with tool assignment
- Use `get_logger()` from `pi_logger` for logging (NOT standard `logging.getLogger()`)
- The logger supports `tag` parameter: `logger.info("message", tag="AgentName")`

### Tool System
- 23 tools defined across 4 categories: technical, fundamental, sentiment, market data
- Tools are Pydantic models with `@tool` decorator
- Assigned to agents based on role in `agent_factory.py`
- Tools can be called by LLM via function calling

### State Management
- `SharedStateManager`: Thread-safe shared state storage
- `StateMachine`: Decision flow state tracking (ANALYZING → DEBATING → ASSESSING_RISK → PLANNING → COMPLETED)
- `EventQueue`: Priority queue for trigger events (CRITICAL > HIGH > MEDIUM > LOW)

### Trigger System
- Extensible trigger system via `trigger_registry.register()`
- Triggers check conditions and return `TriggerEvent` when triggered
- Priority levels determine handling: CRITICAL (auto-execute), HIGH (suggest), MEDIUM/LOW (log only)

### LLM Integration
- Use `stream_simple()` for basic streaming responses
- Model router automatically selects models based on whether tools are needed
- Concurrent LLM calls are limited via Semaphore (default: 3 concurrent) to avoid rate limiting
- Credit tracking available for billing (optional)

### Data Sources
- `BinanceClient`: WebSocket and REST API client for market data
- `KlineStorage`: SQLite-based K-line data persistence
- `MacroStorage`: SQLite-based macro state storage
- `RateLimiter`: Token bucket rate limiter (2400 requests/minute)

## Important Notes

### Logging
- **Always use `pi_logger`**: `from pi_logger import get_logger; logger = get_logger(__name__)`
- **Never use standard logging**: `logging.getLogger(__name__)` does NOT support the `tag` parameter
- Standard logging causes `TypeError: info() got an unexpected keyword argument 'tag'` errors

### Agent Development
- Agents should be async and use `agent.prompt()` for user messages
- Use `ToolContext` to pass shared resources (symbol, interval, storage, etc.)
- Agent prompts are in `config/prompts.py`
- Use `setup_streaming()` for streaming event callbacks

### Testing
- Test files are in root directory (not backend/src)
- Tests use real market data from Binance
- Some tests require API keys in `.env`

### Database
- Uses SQLite with aiosqlite for async operations
- Migrations in `data_sources/migrations/`
- Tables: klines, macro_states, trigger_configs, trigger_events, decisions

### Multi-threading
- Three independent threads communicate via shared state and message passing
- Emergency mode pauses main thread for critical events
- Use `ThreadManager` to manage thread lifecycle


# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


## 🧠 Layered Memory & Cognitive Workflow (Mandatory Principles)
You must actively traverse and respect the three cognitive memory layers before reasoning or executing commands:

1. **L0: Working Memory (Session & Developer Context)** — `claude-mem`
   - **Action**: Always respect developer habits and session checkpoints injected via `claude-mem`. If `claude-mem` is unavailable (e.g. in Kilo, OpenClaw, OpenCode, Claude Desktop, Pi Agent), fall back to active chat session history and local scratchpads (e.g. active notes or current document) to maintain short-term state.
   - **Purpose**: Maintain task continuity and follow local guidelines for the active coding session.
   - **Lifecycle**: Session-bound, auto-compacted.

2. **L1: Structural Memory (Codebase Topology)** — `codebase-memory-mcp`
   - **Action**: ALWAYS prefer `codebase-memory-mcp` graph tools over grep/glob/file-search for code discovery. Use them in this priority order:
     1. `search_graph` — find functions, classes, routes, variables by pattern
     2. `trace_path` — trace who calls a function or what it calls
     3. `get_code_snippet` — read specific function/class source code
     4. `query_graph` — run Cypher queries for complex patterns
     5. `get_architecture` — high-level project summary
   - **Fallback to grep/glob** only when: searching string literals/error messages, non-code files (Dockerfiles, shell scripts), or when MCP tools return insufficient results.
   - **Non-Text Documents**: Non-plain-text docs (PDF, Docx, Xlsx) in docs/ are parsed into markdown in `.ai-brain/parsed-docs/`. Proactively read them when analyzing specifications.
   - **Purpose**: Full code indexing — functions, classes, call graphs, dependencies.
   - **Lifecycle**: Project-bound, rebuilt on `git pull`/`checkout`. **This is where code lives.**

3. **L2: Long-Term Memory (Historical Memory Palace)** — `mempalace`
   - **Action**: Before answering queries about system design, past debugging history, environment setups, or business logic, proactively query the memory database using:
     - `mempalace_search` — semantic full-text search across all memories
     - `mempalace_kg_query` — structured knowledge graph query
     - `mempalace_traverse` — traverse connected entities
     - `mempalace_get_drawer` — retrieve a specific memory by ID
   - **Project Boundary Isolation**: Always restrict or prioritize memory searches to the active project's specific wing (or filter by workspace keyword). Do NOT bleed architectural decisions or debug context from unrelated projects into the current workspace.
   - **Purpose**: High-value persistent knowledge — conversations, architecture decisions, debug war stories, environment configs, lessons learned.
   - **Lifecycle**: Cross-project, permanent.
   - **⚠️ IMPORTANT**: Do NOT mine entire codebases into mempalace. L2 is for curated, high-value memories only. Code indexing belongs in L1 (codebase-memory-mcp). Use `ai-brain mine` to selectively add specific content.

## 🎨 Global Developer Preferences
- **Coding Style**: PEP 8 for Python, standard formatting for Go
- **Memory Priorities**: L0 (Working Memory) > L1 (Codebase Topology) > L2 (Long-Term Memory)
