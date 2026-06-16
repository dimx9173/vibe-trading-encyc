"""
P0.1 — Reflection memory loop.

C1: prove the reflection subsystem actually persists to memory and round-trips
through retrieval. The existing skeleton was silently broken (TradeReflector
called non-existent memory.add/search with collection=, and the coordinator
awaited a sync add_memory with wrong kwargs). These tests pin the corrected
behaviour.
"""
import pytest

from vibe_trading.memory.memory import PersistentMemory
from vibe_trading.memory.reflection import (
    ReflectionOutcome,
    TradeResult,
    TradeReflector,
    compute_alpha,
)


def _make_trade_result(pnl_percentage: float = 3.0) -> TradeResult:
    return TradeResult(
        symbol="ETHUSDT",
        decision="BUY",
        entry_price=100.0,
        exit_price=100.0 * (1 + pnl_percentage / 100.0),
        position_size=1.0,
        pnl=pnl_percentage,
        pnl_percentage=pnl_percentage,
        hold_duration_hours=2.0,
        market_condition="trending",
    )


async def test_reflection_persists_to_memory_and_retrieves(tmp_path):
    """reflect_on_trade must persist entries retrievable by situation."""
    memory = PersistentMemory(storage_path=str(tmp_path / "mem.pkl"))
    reflector = TradeReflector(memory=memory, llm_model=None)  # rules-based, no LLM call

    await reflector.reflect_on_trade(
        trade_result=_make_trade_result(3.0),
        agent_reports={"technical_analyst": "ETHUSDT uptrend, RSI healthy, buy"},
        decision_context={"decision_id": "d1"},
    )

    assert memory.size() > 0, "reflection produced no persisted memory entries"

    hits = memory.retrieve_relevant("ETHUSDT BUY trending", top_k=3)
    assert hits, "retrieve_relevant returned nothing after a reflection"
    assert any("ETHUSDT" in h for h in hits)


async def test_reflection_survives_reload(tmp_path):
    """Persisted reflections must survive a save/load cycle (cross-session)."""
    path = str(tmp_path / "mem.pkl")
    memory = PersistentMemory(storage_path=path)
    reflector = TradeReflector(memory=memory, llm_model=None)

    await reflector.reflect_on_trade(
        trade_result=_make_trade_result(-4.0),
        agent_reports={"technical_analyst": "ETHUSDT breakdown, sell"},
        decision_context={"decision_id": "d2"},
    )
    memory.save()
    assert path  # exists

    reloaded = PersistentMemory(storage_path=path)
    assert reloaded.load()
    assert reloaded.size() > 0
    hits = reloaded.retrieve_relevant("ETHUSDT SELL", top_k=3)
    assert hits


# ---------------------------------------------------------------------------
# C2: benchmark alpha (market-adjusted decision quality)
# ---------------------------------------------------------------------------

def test_compute_alpha_pure_helper():
    """alpha = decision pnl% - benchmark return%."""
    assert compute_alpha(5.0, 8.0) == -3.0          # gained but underperformed market
    assert compute_alpha(5.0, 0.0) == 5.0           # no benchmark move
    assert compute_alpha(None, 8.0) is None         # no pnl → no alpha
    assert compute_alpha(5.0, None) is None         # no benchmark → no alpha


def _make_trade_result_with_alpha(pnl_percentage, benchmark_return):
    tr = _make_trade_result(pnl_percentage)
    tr.benchmark_return = benchmark_return
    tr.alpha = compute_alpha(pnl_percentage, benchmark_return)
    return tr


def test_outcome_uses_alpha_when_present():
    """When alpha is available it drives the verdict, not raw pnl."""
    reflector = TradeReflector(memory=PersistentMemory(storage_path="/tmp/_unused.pkl"))

    # gained 5% but BTC did 9% → alpha -4% → underperformed market → INCORRECT
    tr = _make_trade_result_with_alpha(5.0, 9.0)
    assert reflector._evaluate_outcome(tr) == ReflectionOutcome.INCORRECT

    # gained 5%, BTC flat → alpha +5% → CORRECT
    tr2 = _make_trade_result_with_alpha(5.0, 0.0)
    assert reflector._evaluate_outcome(tr2) == ReflectionOutcome.CORRECT


def test_outcome_falls_back_to_raw_pnl_without_alpha():
    """No alpha → legacy raw-pnl thresholds preserved."""
    reflector = TradeReflector(memory=PersistentMemory(storage_path="/tmp/_unused.pkl"))
    assert reflector._evaluate_outcome(_make_trade_result(3.0)) == ReflectionOutcome.CORRECT
    assert reflector._evaluate_outcome(_make_trade_result(-4.0)) == ReflectionOutcome.INCORRECT


async def test_reflection_persists_and_surfaces_alpha(tmp_path):
    """Alpha must be stored on the memory entry and shown in retrieved text."""
    memory = PersistentMemory(storage_path=str(tmp_path / "mem.pkl"))
    reflector = TradeReflector(memory=memory, llm_model=None)

    await reflector.reflect_on_trade(
        trade_result=_make_trade_result_with_alpha(5.0, 9.0),  # alpha -4%
        agent_reports={"technical_analyst": "ETHUSDT strong, buy"},
        decision_context={"decision_id": "d3"},
    )

    entries = memory.get_all_memories()
    assert entries, "no memory entries persisted"
    assert any(e.alpha is not None for e in entries), "alpha not persisted on any entry"

    hits = memory.retrieve_relevant("ETHUSDT BUY", top_k=5)
    assert hits
    assert any("Alpha" in h for h in hits), "retrieved text does not surface alpha"
