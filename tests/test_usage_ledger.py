"""Tests for usage ledger - LLM cost tracking."""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from vibe_trading.monitoring.usage_ledger import (
    UsageLedger,
    UsageEntry,
    UsageSummary,
    get_usage_ledger,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Create temporary database path."""
    return tmp_path / "test_usage.db"


@pytest.fixture
def ledger(tmp_db):
    """Create fresh usage ledger for testing."""
    return UsageLedger(db_path=str(tmp_db))


class TestUsageLedger:
    """Test usage ledger core functionality."""

    async def test_record_usage_creates_entry(self, ledger):
        """Recording usage should create a new entry."""
        entry = await ledger.record_usage(
            agent_name="technical_analyst",
            model="deepseek-v3",
            symbol="BTCUSDT",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.015,
        )

        assert entry.agent_name == "technical_analyst"
        assert entry.model == "deepseek-v3"
        assert entry.symbol == "BTCUSDT"
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.cost_usd == 0.015
        assert entry.id is not None

    async def test_record_usage_with_timestamp(self, ledger):
        """Recording usage with explicit timestamp should use that timestamp."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        entry = await ledger.record_usage(
            agent_name="pm",
            model="gpt-4",
            symbol="ETHUSDT",
            input_tokens=2000,
            output_tokens=1000,
            cost_usd=0.05,
            timestamp=ts,
        )

        assert entry.timestamp == ts

    async def test_get_summary_empty_ledger(self, ledger):
        """Empty ledger should return zero summary."""
        summary = await ledger.get_summary()

        assert summary.total_requests == 0
        assert summary.total_input_tokens == 0
        assert summary.total_output_tokens == 0
        assert summary.total_cost_usd == 0.0

    async def test_get_summary_aggregates_entries(self, ledger):
        """Summary should aggregate all entries."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015)

        summary = await ledger.get_summary()

        assert summary.total_requests == 3
        assert summary.total_input_tokens == 450
        assert summary.total_output_tokens == 225
        assert abs(summary.total_cost_usd - 0.045) < 1e-9

    async def test_get_summary_by_agent(self, ledger):
        """Summary by agent should filter and aggregate correctly."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015)

        agent1_summary = await ledger.get_summary(agent_name="agent1")

        assert agent1_summary.total_requests == 2
        assert agent1_summary.total_input_tokens == 250
        assert agent1_summary.total_output_tokens == 125
        assert abs(agent1_summary.total_cost_usd - 0.025) < 1e-9

    async def test_get_summary_by_model(self, ledger):
        """Summary by model should filter and aggregate correctly."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015)

        model1_summary = await ledger.get_summary(model="model1")

        assert model1_summary.total_requests == 2
        assert model1_summary.total_input_tokens == 300
        assert model1_summary.total_output_tokens == 150
        assert abs(model1_summary.total_cost_usd - 0.03) < 1e-9

    async def test_get_summary_by_symbol(self, ledger):
        """Summary by symbol should filter and aggregate correctly."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015)

        btc_summary = await ledger.get_summary(symbol="BTCUSDT")

        assert btc_summary.total_requests == 2
        assert btc_summary.total_input_tokens == 250
        assert btc_summary.total_output_tokens == 125
        assert abs(btc_summary.total_cost_usd - 0.025) < 1e-9

    async def test_get_summary_with_time_range(self, ledger):
        """Summary with time range should filter entries by timestamp."""
        ts1 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        ts3 = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01, timestamp=ts1)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02, timestamp=ts2)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015, timestamp=ts3)

        # Query between 10:30 and 11:30
        start = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 11, 30, 0, tzinfo=timezone.utc)
        summary = await ledger.get_summary(start_time=start, end_time=end)

        assert summary.total_requests == 1
        assert summary.total_input_tokens == 200
        assert summary.total_output_tokens == 100
        assert abs(summary.total_cost_usd - 0.02) < 1e-9

    async def test_get_daily_summary(self, ledger):
        """Daily summary should aggregate by date."""
        # 固定時間戳避免 UTC 凌晨跨日 (now-6h 落在昨天)
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        ts1 = now - timedelta(hours=2)  # Today
        ts2 = now - timedelta(hours=6)  # Today
        ts3 = now - timedelta(hours=20)  # Yesterday (08-14 16:00, 在 days=2 cutoff 內)

        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01, timestamp=ts1)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02, timestamp=ts2)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 150, 75, 0.015, timestamp=ts3)

        daily = await ledger.get_daily_summary(days=2)

        assert len(daily) == 2
        # Most recent day first
        assert daily[0].total_requests == 2  # Today
        assert daily[1].total_requests == 1  # Yesterday

    async def test_get_top_agents(self, ledger):
        """Top agents should return agents sorted by usage."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 300, 150, 0.03)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent3", "model1", "BTCUSDT", 50, 25, 0.005)

        top_agents = await ledger.get_top_agents(limit=2)

        assert len(top_agents) == 2
        assert top_agents[0].agent_name == "agent1"
        assert top_agents[0].total_requests == 2
        assert top_agents[1].agent_name == "agent2"
        assert top_agents[1].total_requests == 1

    async def test_get_top_models(self, ledger):
        """Top models should return models sorted by usage."""
        await ledger.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)
        await ledger.record_usage("agent2", "model1", "ETHUSDT", 200, 100, 0.02)
        await ledger.record_usage("agent1", "model2", "BTCUSDT", 50, 25, 0.005)

        top_models = await ledger.get_top_models(limit=2)

        assert len(top_models) == 2
        assert top_models[0].model == "model1"
        assert top_models[0].total_requests == 2
        assert top_models[1].model == "model2"
        assert top_models[1].total_requests == 1

    async def test_persistence_across_instances(self, tmp_db):
        """Usage data should persist across ledger instances."""
        ledger1 = UsageLedger(db_path=str(tmp_db))
        await ledger1.record_usage("agent1", "model1", "BTCUSDT", 100, 50, 0.01)

        # Create new instance with same db
        ledger2 = UsageLedger(db_path=str(tmp_db))
        summary = await ledger2.get_summary()

        assert summary.total_requests == 1
        assert summary.total_input_tokens == 100

    async def test_estimate_cost(self, ledger):
        """Cost estimation should use model pricing."""
        cost = ledger.estimate_cost(
            model="gpt-4",
            input_tokens=1000,
            output_tokens=500,
        )

        # GPT-4: $30/1M input, $60/1M output
        expected = (1000 / 1_000_000) * 30 + (500 / 1_000_000) * 60
        assert abs(cost - expected) < 1e-9

    async def test_estimate_cost_unknown_model(self, ledger):
        """Unknown model should return zero cost."""
        cost = ledger.estimate_cost(
            model="unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )

        assert cost == 0.0


class TestGlobalUsageLedger:
    """Test global usage ledger singleton."""

    async def test_get_usage_ledger_returns_singleton(self):
        """get_usage_ledger should return the same instance."""
        ledger1 = get_usage_ledger()
        ledger2 = get_usage_ledger()

        assert ledger1 is ledger2

    async def test_global_ledger_is_initialized(self):
        """Global ledger should be initialized and usable."""
        ledger = get_usage_ledger()

        assert ledger is not None
        summary = await ledger.get_summary()
        assert summary is not None
