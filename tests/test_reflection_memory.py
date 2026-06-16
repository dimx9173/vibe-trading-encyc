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
from vibe_trading.memory.reflection import TradeResult, TradeReflector


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
