---
title: PI Platform Conformance
description: PI 平台一致性規範與合規檢查
date: 2026-08-05
category: architecture
tags: [pi-platform, conformance, standards, compliance]
summary: |
  PI 平台一致性規範，定義 Agent 框架、LLM 整合、Tool 系統的標準介面與合規要求。
---

# Vibe-Trading × pi-Platform-Skills — Architecture Conformance Review

> ⚠️ **歷史設計評審（2026-08-05）**：本評審早於 2026-08-28「印鈚機優先收斂計畫」。收斂後系統改為 Binance 單交易所、規則層主引擎 + LLM 每小時 regime gate；原 `prime` 監控模式與 MCP server 已於階段 0 物理刪除。下方關於 Prime mode「partially built」等描述現已不適用（功能已移除，非部分建置）。

**Scope:** Design-level (architecture) review only. Not a code/implementation verification.
**Method:** Follows `verify-agent-platform` SKILL.md rules — capabilities reconstructed from
**vibe-trading's own design** (README, AGENTS.md, ROADMAP.md, docs/guide/*), never from the
skill pack's own TS architecture. Absent optional profiles are reported as **N/A**, not failures.
**Skill pack version:** installed via `install.sh` from `encyc/pi-platform-skills@main` (5 skills).

---

## 0. Framing — what this report is and is not

The `pi-platform-skills` pack targets **greenfield TypeScript** agent platforms ("Keep Agent core
code TypeScript", `build-agent-platform/SKILL.md:48-49`). Vibe-trading is a **Python** multi-agent
crypto-trading system. So:

- The **literal** TS invariant cannot pass for a Python project. The review judges the **principle**
  behind it ("the platform owns its typed contracts and isolates the runtime behind an adapter",
  `architecture.md:29-31`) rather than the language.
- The optional **profiles** (InsForge, BFF, MCP, nginx/Compose, durable Sessions) are reported
  **N/A — not claimed by this project's design**, per `verify SKILL.md:13-15` ("Do not use
  pi-platform-skills's own architecture as the catalog") and `verification-matrix.md:3`
  ("Select only categories applicable to the approved design").

What vibe-trading **claims** (from its own docs): a pi-agent-core-based 12-agent / 4-phase crypto
trading pipeline (enum+factory, not registry); a hardcoded per-role tool assignment; in-memory
shared state (no durable sessions, no resume); a 3-thread realtime model with priority queue +
emergency pause; BM25 memory + LLM reflection loop; an extensible trigger registry; a dual-model
selection scheme; a FastAPI+WebSocket **monitoring dashboard** (not an Agent Server); a typer CLI.
It **does not claim** a skill system, durable Sessions, MCP, BFF, nginx, Docker/k8s, multi-tenant,
OKX live execution, or a real backtest engine.

---

## 1. Profile applicability

| Skill profile | Applicable? | Reason |
| --- | --- | --- |
| **Core** (pi adapter, registries, delegation, sessions, server, CLI) | **Partial** — concepts portable | Vibe-trading has a runtime, agents, tools, state, CLI. Lacks registries, delegation primitive, unified server. |
| **Production** (external adapters, durable sessions, BFF, observability, deploy) | **N/A** | Not claimed. No Dockerfile/compose/k8s exist. Web UI is a monitor, not an authenticated BFF. |
| **MCP** (remote tool import) | **N/A** | Not claimed. P1 roadmap goal only (`ROADMAP.md`). |
| **InsForge** (auth/db/storage) | **N/A** | Not claimed. Single-user, env-var keys, no auth layer. |
| **BFF** (browser auth boundary) | **N/A** | Not claimed. WebSocket dashboard, no cookie/token boundary. |
| **nginx/deploy** | **N/A** | Not claimed. Docs mention docker-compose aspirationally; no artifacts exist. |

---

## 2. Core invariants — conformance matrix

The 10 conceptually-portable invariants from `build-agent-platform/SKILL.md:47-60` and
`core-runtime.md`. Verdicts: **Pass / Partial / Gap / N/A**.

| # | Invariant (skill source) | Verdict | Evidence in vibe-trading | Gap |
| --- | --- | --- | --- | --- |
| 1 | **Single Agent definition; supervisor via grant, not separate class** (`build:51-52`, `core-runtime:25-27`) | **Partial** | One base: all agents subclass `pi_agent_core.Agent` (`agent_factory.py:9`, 12 agent files). BUT: (a) production path is a fixed 4-phase `TradingCoordinator` pipeline, not delegation; (b) alternate "Prime" mode is a hub-and-spoke monitor pattern (`prime/prime_agent.py:44`), not a `delegate_to_agent` primitive (`grep delegate/dispatch/forward` in `prime/*.py` → none). Several Prime subagents are `enabled=False` stubs (`subagent_factory.py:55,63,70`). | No `delegate_to_agent` tool. Supervisor concept is implicit (coordinator + prime hub), not modeled as a grant. |
| 2 | **Central tool registry + explicit per-agent grants** (`build:53`, `core-runtime:29-39`) | **Partial** | Central list exists: `get_all_tools()` (`agent_tools.py:759`, ~24 tools). BUT grants are a hardcoded `if/elif role ==` chain (`get_tools_for_agent`, `agent_tools.py:940-1030`), not a registry abstraction. Execution tool is gated separately via `ToolContext` injection (`create_submit_trade_order_tool`), which is the right instinct. | No registry object; grants are procedural. README says 23 tools, code says 24 — doc drift. |
| 3 | **Runtime/LLM isolated behind an adapter; platform owns its types** (`architecture:29-31`, `core-runtime:5-17`) | **Partial** | LLM isolation is clean via `pi_ai` (providers, streaming, retry). BUT `vibe_trading` imports pi symbols directly — `from pi_agent_core import Agent, AgentOptions, AgentTool` (`agent_factory.py:9-10`, etc.), `from pi_ai.config import get_model_from_config` (9 files). No platform-owned type boundary; the app is coupled to pi's message/event/tool types. | No runtime adapter layer; app speaks pi types natively. (Acceptable for a single-runtime app, but does not meet the invariant literally.) |
| 4 | **Skills don't expand tool grants / skill system** (`build:57`, `core-runtime:46-53`) | **N/A** | Project claims no skill system. "Skill" appears only in the external `.agents/skills/` dir and as a P3 roadmap aspiration (`ROADMAP.md:123-128`, marked 🔴 missing). | N/A — not adopted by design. |
| 5 | **Core independent of external infra** (`build:58`) | **Pass** | Core depends only on Binance (data+execution) and LLM providers. No BFF, MCP, InsForge, nginx coupling. Web layer is a side-channel monitor, not a dependency of the decision loop. | None. |
| 6 | **Business logic in the target project** (`build:59-60`) | **Pass** | All 12 agents' prompts, the 24 tool schemas, data schemas, model choices, and the `agent_model_mapping` live in `vibe_trading/`. The pi packages carry no trading logic. | None. |
| 7 | **Single composition root** (`architecture:30`, `core-runtime:78-79`) | **Partial** | Multiple independent entry points: `TradingCoordinator` (prod pipeline), `PrimeAgent` (alt hub-and-spoke mode), FastAPI web server (monitoring), typer CLI (`start/analyze/prime/status/macro`). They do not share one application service — the CLI drives the coordinator directly, the web layer reads shared state + journal, Prime is a separate mode. | No unified composition root; 4 entry points with overlapping but distinct orchestration. |
| 8 | **Sessions sized to actual need** (`build:67-69`, `core-runtime:55-64`) | **Pass** | In-memory `SharedStateManager` (`coordinator/shared_state.py:49`, `Dict[str, StateEntry]` + asyncio.Lock + TTL + pub/sub) and in-memory `DecisionStateMachine`. No restart continuity claimed; no leases/fencing/ledger. SQLite tables (`klines`, `decisions`, `bar_decision_journal`) are for data + display/replay, not session resume. Matches "do not over-build." | None for current scope. (P1 roadmap notes per-node persistence+resume as a future gap — correctly deferred.) |
| 9 | **Startup-time validation of registries** (`core-runtime:21-23`) | **Gap** | No registry-time validation of duplicate agent IDs, unknown tool references, or invalid model config. `get_tools_for_agent` silently falls through to a 3-tool default for unknown roles (`agent_tools.py:1025-1030`). Bad model name in `llm.yaml` would fail at first LLM call, not at startup. | No startup validation step. |
| 10 | **No premature distributed machinery** (`architecture:46-48`) | **Pass** | 3 in-process asyncio threads (macro/on-bar/event) communicate via shared state + message passing (`thread_manager.py`). No Kubernetes, distributed locks, event sourcing, multi-region, or policy engine. Emergency mode is a simple pause flag. | None. |

**Core scorecard: 4 Pass · 4 Partial · 1 Gap · 1 N/A.** The Partials are all "the concept is
half-realized procedurally rather than as an abstraction" — consistent with a focused trading app
that did not set out to build a general agent platform.

---

## 3. Verification categories — design-level applicability

From `verification-matrix.md:5-17`. "Establish at design level" = the design *commits to and
structurally supports* the behavior.

| Category | Applicable? | Design-level assessment |
| --- | --- | --- |
| typecheck/build | **Yes** | Public contracts exist (Agent/AgentOptions/AgentTool) but are pi-owned, not platform-owned. `mypy backend/src/` is configured (AGENTS.md). |
| unit | **Yes** | Registries/mappings/error-normalization are partly testable; `get_tools_for_agent` role mapping is pure logic. Limited unit test coverage today (tests are mostly integration with real Binance data). |
| runtime integration | **Yes** | pi adapter completes/streams/cancels via `agent.prompt()` + `agent.subscribe()` + `agent.abort()`. Usage reporting is a P0.3 roadmap gap (`ROADMAP.md:55-60`) — not yet claimed. |
| Tool integration | **Yes** | Grants (procedural), built-ins (24 tools), limits (risk-gate in submit tool), cancellation (cancel_event). No delegation tool. |
| Skill integration | **N/A** | No skill system claimed. |
| Session integration | **Partial** | In-memory only; no restart/ownership/concurrency-persistence claimed. Correctly scoped, but the "restart continuity" sub-behavior is absent by design. |
| HTTP/SSE | **N/A (different shape)** | Project uses WebSocket (`ws://…/ws`) for a monitoring dashboard, not SSE, and it is not an "Agent Server." The dashboard does not run agents — it observes shared state + journal. So the skill's HTTP/SSE category (validation, event order, terminal behavior, disconnect, shutdown of an agent-running server) does not apply. |
| InsForge | **N/A** | Not claimed. |
| BFF | **N/A** | Not claimed. |
| MCP | **N/A** | Not claimed (P1 goal). |
| deployment | **N/A** | Not claimed; no artifacts. |

---

## 4. The literal "TypeScript core" invariant

`build-agent-platform/SKILL.md:48-49`: *"Keep Agent core code TypeScript."*

- **Literal verdict: does not apply.** Vibe-trading is Python; its agent core (`pi_agent_core`/
  `pi_ai`) is a Python port of the TS pi framework.
- **Principle verdict: Partial.** The principle behind the invariant — "the platform owns its own
  typed contracts and keeps the runtime behind an adapter" (`architecture.md:29-31`) — is
  half-met. LLM specifics are isolated (good), but the app imports pi's `Agent`/`AgentTool`/
  message types directly rather than through platform-owned ports (see invariant #3).

**Recommendation if literal conformance is ever desired:** introduce a thin `vibe_trading.runtime`
adapter exposing app-owned `TradingAgent`/`Tool`/`Event` types, with pi as one swappable backend.
This is the single change that would move invariants #3 and the TS-principle from Partial toward Pass.
It is **not required** for the project to function correctly today.

---

## 5. Residual risks (not converted into successes)

1. **Multiple composition roots** (invariant #7) — Prime mode, prod pipeline, web, CLI can drift
   independently. No stated invariant that they share orchestration. Risk: behavioral divergence
   between `vibe-trade analyze` and the web dashboard's view of a decision.
2. **No startup validation** (invariant #9) — misconfigured model/tool/role fails late (at runtime),
   not early. Low blast radius for a single-user trading bot, but it violates the skill's
   "validate at startup" invariant.
3. **Prime mode is partially built** — several subagents `enabled=False`. The hub-and-spoke design
   is documented as an alternate mode but is not the production path. Anyone reading the skill's
   "supervisor" invariant could mistake Prime for a delegation system; it is not.
4. **Doc drift** — README says 23 tools, code says 24; `agent_model_mapping` exists in `llm.yaml`
   but is currently inert (no call site passes `agent_role` to the router). These are accuracy
   issues in the design record, not runtime bugs.

---

## 6. Conclusion

Vibe-trading is **a well-scoped domain application, not a general agent platform**, and it does
not claim to be one. Measured against the skill pack's *portable design principles*, it passes the
independence/scoping/business-logic invariants cleanly, partially meets the agent/tool/runtime
invariants (realized procedurally rather than as abstractions), and has one genuine gap
(startup validation). The optional profiles (InsForge/BFF/MCP/nginx/durable-sessions) are honestly
N/A — the project never adopted them and should not be penalized for their absence.

**No change to the project's architecture is required by this review.** The two highest-value
*optional* improvements, if desired, are: (a) a thin runtime adapter to satisfy invariant #3 and
the TS principle; (b) a startup validation pass to close invariant #9. Both are independent of the
pi-py migration.
