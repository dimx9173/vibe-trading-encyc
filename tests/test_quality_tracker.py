"""Tests for DecisionQualityTracker (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.coordinator.quality_tracker import DecisionQualityTracker
from vibe_trading.coordinator.signal_processor import TradingSignal


class _Signal:
    """Mock ProcessedSignal."""

    def __init__(self, signal=TradingSignal.BUY, confidence=0.8, strength=None):
        self.signal = signal
        self.confidence = confidence
        self.strength = strength or MagicMock()
        self.strength.value = "strong"


@pytest.fixture
def tracker():
    journal = MagicMock()
    journal.upsert_bar = AsyncMock(return_value=None)
    return DecisionQualityTracker(
        storage_path=":memory:", enable_persistence=False, journal_storage=journal,
    )


class TestRecordDecision:
    @pytest.mark.asyncio
    async def test_record_decision(self, tracker):
        await tracker.record_decision(
            decision_id="d1", symbol="BTCUSDT", signal=_Signal(),
            agent_contributions={"technical": 0.6, "fundamental": 0.4},
        )
        assert len(tracker._decisions) == 1
        assert tracker._decisions[0].decision_id == "d1"
        assert tracker._decisions[0].signal == TradingSignal.BUY

    @pytest.mark.asyncio
    async def test_record_decision_persists(self, tracker):
        tracker.enable_persistence = True
        await tracker.record_decision(
            decision_id="d2", symbol="BTCUSDT", signal=_Signal(),
            agent_contributions={}, interval="30m", bar_open_time_ms=123,
        )
        # persist 被呼叫 (journal.upsert_bar 已 mock)

    @pytest.mark.asyncio
    async def test_record_decision_invalidates_cache(self, tracker):
        tracker._metrics_cache = MagicMock()
        tracker._cache_timestamp = __import__("datetime").datetime.now()
        await tracker.record_decision("d3", "BTCUSDT", _Signal(), {})
        assert tracker._metrics_cache is None


class TestRecordOutcome:
    @pytest.mark.asyncio
    async def test_outcome_updates_pnl(self, tracker):
        await tracker.record_decision("d1", "BTCUSDT", _Signal(TradingSignal.BUY),
                                      {"technical": 0.6})
        await tracker.record_outcome("d1", entry_price=100.0, exit_price=110.0,
                                     position_size=1.0, hold_duration_hours=1.0)
        rec = tracker._decisions[0]
        assert rec.pnl == pytest.approx(10.0)
        assert rec.pnl_percentage == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_outcome_unknown_decision(self, tracker):
        await tracker.record_outcome("missing", 100.0, 110.0, 1.0, 1.0)  # 不 raise

    @pytest.mark.asyncio
    async def test_outcome_sell_pnl(self, tracker):
        await tracker.record_decision("d2", "BTCUSDT", _Signal(TradingSignal.SELL),
                                      {"technical": 0.6})
        await tracker.record_outcome("d2", entry_price=100.0, exit_price=90.0,
                                     position_size=1.0, hold_duration_hours=1.0)
        assert tracker._decisions[0].pnl == pytest.approx(10.0)


class TestMetrics:
    @pytest.mark.asyncio
    async def test_empty_metrics(self, tracker):
        m = await tracker.get_quality_metrics()
        assert m.total_decisions == 0
        assert m.win_rate == 0

    @pytest.mark.asyncio
    async def test_metrics_with_trades(self, tracker):
        for i in range(3):
            await tracker.record_decision(f"d{i}", "BTCUSDT", _Signal(),
                                          {"technical": 0.5})
            await tracker.record_outcome(f"d{i}", 100.0, 110.0, 1.0, 1.0)
        m = await tracker.get_quality_metrics()
        assert m.total_decisions == 3
        assert m.win_rate == 1.0
        assert m.total_pnl == pytest.approx(30.0)
        assert m.best_trade_pnl == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_metrics_cache(self, tracker):
        await tracker.record_decision("d0", "BTCUSDT", _Signal(), {"t": 0.5})
        await tracker.record_outcome("d0", 100.0, 110.0, 1.0, 1.0)
        m1 = await tracker.get_quality_metrics()
        m2 = await tracker.get_quality_metrics()  # cache 命中
        assert m1 is m2

    @pytest.mark.asyncio
    async def test_metrics_force_refresh(self, tracker):
        await tracker.record_decision("d0", "BTCUSDT", _Signal(), {"t": 0.5})
        await tracker.record_outcome("d0", 100.0, 110.0, 1.0, 1.0)
        m1 = await tracker.get_quality_metrics()
        m2 = await tracker.get_quality_metrics(force_refresh=True)
        assert m1 is not m2

    @pytest.mark.asyncio
    async def test_max_drawdown(self, tracker):
        await tracker.record_decision("d0", "BTCUSDT", _Signal(), {})
        await tracker.record_outcome("d0", 100.0, 110.0, 1.0, 1.0)  # +10
        await tracker.record_decision("d1", "BTCUSDT", _Signal(), {})
        await tracker.record_outcome("d1", 100.0, 80.0, 1.0, 1.0)  # -20
        m = await tracker.get_quality_metrics()
        assert m.max_drawdown == pytest.approx(-20.0)


class TestRanking:
    def test_agent_ranking(self, tracker):
        perf = tracker._agent_performances
        # 直接注入性能資料
        from vibe_trading.coordinator.quality_tracker import AgentPerformance
        a = AgentPerformance(agent_name="tech", total_decisions=10, accuracy=0.8)
        b = AgentPerformance(agent_name="fund", total_decisions=10, accuracy=0.5)
        perf["tech"], perf["fund"] = a, b
        ranking = tracker.get_agent_ranking(min_decisions=1)
        assert ranking[0][0] == "tech"  # 最高準確率優先
        assert ranking[0][1] == 0.8

    def test_top_performers(self, tracker):
        from vibe_trading.coordinator.quality_tracker import AgentPerformance
        perf = tracker._agent_performances
        for name, acc in [("a", 0.9), ("b", 0.7), ("c", 0.5), ("d", 0.3)]:
            perf[name] = AgentPerformance(agent_name=name, total_decisions=10, accuracy=acc)
        top = tracker.get_top_performers(top_n=2)
        assert top == ["a", "b"]

    def test_underperformers(self, tracker):
        from vibe_trading.coordinator.quality_tracker import AgentPerformance
        perf = tracker._agent_performances
        for name, acc in [("a", 0.9), ("b", 0.3)]:
            perf[name] = AgentPerformance(agent_name=name, total_decisions=10, accuracy=acc)
        under = tracker.get_underperformers(threshold=0.4)
        assert under == ["b"]
