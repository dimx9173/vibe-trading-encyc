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


# ---------------------------------------------------------------------------
# C3: per-bar Portfolio Manager memory injection
# ---------------------------------------------------------------------------
from types import SimpleNamespace  # noqa: E402

from vibe_trading.agents.decision.decision_agents import PortfolioManagerAgent  # noqa: E402
from vibe_trading.agents.decision.trading_tools import (  # noqa: E402
    DecisionScorecard,
    ExecutionStyle,
    PositionSide,
    TradingPlan,
)


def _make_pm(symbol="ETHUSDT", memory=None):
    pm = PortfolioManagerAgent()
    pm._tool_context = SimpleNamespace(symbol=symbol, interval="30m")
    pm._memory = memory
    return pm


def _make_scorecard(action="BUY", rationale="ETHUSDT uptrend continuation"):
    return DecisionScorecard(
        overall_score=60.0,
        confidence=0.7,
        technical_score=65.0,
        fundamental_score=55.0,
        sentiment_score=60.0,
        risk_score=70.0,
        recommended_action=action,
        position_size_recommendation="medium",
        rationale=rationale,
    )


def _make_plan():
    return TradingPlan(
        symbol="ETHUSDT",
        position_side=PositionSide.LONG,
        direction="LONG",
        execution_style=ExecutionStyle.IMMEDIATE,
        entry_orders=[{"order_type": "market", "price": 100.0, "pct": 100, "note": "entry"}],
        total_position_usdt=50.0,
        total_position_coin=0.5,
        leverage=5,
        stop_loss_orders=[{"trigger_price": 98.0, "note": "sl"}],
        take_profit_orders=[{"price": 105.0, "pct": 100, "note": "tp"}],
        max_loss_usdt=1.0,
        max_loss_pct=0.02,
        risk_reward_ratio=2.5,
    )


def test_memory_section_includes_lessons_when_present(tmp_path):
    memory = PersistentMemory(storage_path=str(tmp_path / "m.pkl"))
    memory.add_memory(
        situation="ETHUSDT BUY uptrend RSI healthy",
        advice="LONG | lessons: trail stops in trending markets",
        outcome="PnL: 4.00%",
        pnl=4.0,
        alpha=2.5,
    )
    pm = _make_pm(memory=memory)
    section = pm._build_memory_section(_make_scorecard())
    assert "RELEVANT PAST LESSONS" in section
    assert "trail stops" in section


def test_memory_section_empty_when_no_memory():
    pm = _make_pm(memory=None)
    assert pm._build_memory_section(_make_scorecard()) == ""


def test_decision_prompt_contains_memory_section(tmp_path):
    memory = PersistentMemory(storage_path=str(tmp_path / "m.pkl"))
    memory.add_memory(
        situation="ETHUSDT BUY uptrend",
        advice="LONG | lessons: avoid over-leverage in trend",
        outcome="PnL: 3.00%",
        pnl=3.0,
    )
    pm = _make_pm(memory=memory)
    prompt = pm._build_decision_prompt(
        scorecard=_make_scorecard(),
        analyst_reports={"technical": "ETHUSDT uptrend, buy"},
        investment_plan="accumulate on dips",
        trading_plan=_make_plan(),
        risk_debate={"aggressive": "go long"},
        current_positions=[],
        account_balance=10000.0,
        current_price=100.0,
    )
    assert "RELEVANT PAST LESSONS" in prompt


# ---------------------------------------------------------------------------
# C4: decision-level reflection (incl HOLD)
# ---------------------------------------------------------------------------
from vibe_trading.memory.decision_snapshots import (  # noqa: E402
    DecisionSnapshot,
    DecisionSnapshotStore,
    interval_to_ms,
)
from vibe_trading.memory.reflection import (  # noqa: E402
    evaluate_decision_outcome,
    reflect_on_matured_snapshot,
)


def test_interval_to_ms():
    assert interval_to_ms("30m") == 30 * 60_000
    assert interval_to_ms("1h") == 3_600_000
    assert interval_to_ms("4h") == 4 * 3_600_000
    assert interval_to_ms("1d") == 86_400_000
    assert interval_to_ms("") == 0
    assert interval_to_ms("bogus") == 0


def test_snapshot_store_pop_matured():
    store = DecisionSnapshotStore()
    window_ms = interval_to_ms("1h") * 12  # 12h

    # 3 snapshots at t0, t0+5h, t0+13h(t=now-ish)
    base = 1_000_000
    fresh = DecisionSnapshot("d_fresh", "ETHUSDT", "HOLD", 100.0, base)
    mid = DecisionSnapshot("d_mid", "ETHUSDT", "BUY", 100.0, base + 5 * interval_to_ms("1h"))
    old = DecisionSnapshot("d_old", "ETHUSDT", "SELL", 100.0, base)
    old.bar_open_time_ms = base  # well in the past
    store.record(fresh)
    store.record(mid)
    store.record(old)

    now = base + 13 * interval_to_ms("1h")  # 13h after base
    matured = store.pop_matured(now, window_ms)
    ids = {m.decision_id for m in matured}
    # base and base+5h are >= 12h old → matured; (none here are base+0 vs 13h=13h>=12h yes)
    assert "d_old" in ids
    assert "d_mid" not in ids  # only 8h old
    assert len(store) == 1  # only d_mid remains


def test_evaluate_decision_outcome():
    # BUY gains with price up
    pnl, alpha = evaluate_decision_outcome("BUY", 100.0, 110.0)
    assert pnl == 10.0 and alpha is None
    # SELL loses when price up
    pnl, _ = evaluate_decision_outcome("SELL", 100.0, 110.0)
    assert pnl == -10.0
    # HOLD: no pnl, but alpha reflects opportunity cost vs benchmark
    pnl, alpha = evaluate_decision_outcome("HOLD", 100.0, 110.0, benchmark_return=10.0)
    assert pnl == 0.0 and alpha == -10.0
    # BUY beating benchmark
    pnl, alpha = evaluate_decision_outcome("BUY", 100.0, 110.0, benchmark_return=8.0)
    assert pnl == 10.0 and alpha == 2.0
    # bad inputs
    assert evaluate_decision_outcome("BUY", 0.0, 100.0) == (None, None)


async def test_reflect_on_matured_hold_captures_missed_move(tmp_path):
    """HOLD while market (and benchmark) rose 10% → negative alpha → INCORRECT."""
    memory = PersistentMemory(storage_path=str(tmp_path / "m.pkl"))
    reflector = TradeReflector(memory=memory, llm_model=None)

    snap = DecisionSnapshot(
        decision_id="d_hold",
        symbol="ETHUSDT",
        decision="HOLD",
        price_at_decision=100.0,
        bar_open_time_ms=1_000_000,
    )

    reflections = await reflect_on_matured_snapshot(
        reflector=reflector,
        snapshot=snap,
        exit_price=110.0,           # market +10%
        benchmark_return=10.0,      # BTC +10% → alpha = 0 - 10 = -10
    )
    assert reflections  # at least the overall reflection

    entries = memory.get_all_memories()
    assert entries
    assert any(e.alpha is not None and e.alpha < 0 for e in entries)

    hits = memory.retrieve_relevant("ETHUSDT HOLD", top_k=5)
    assert hits
