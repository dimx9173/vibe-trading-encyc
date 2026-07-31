"""
Tests for decision persistence layer.

Currently broken: TradingCoordinator.record_decision path never calls
DecisionJournalStorage.upsert_bar, so /api/decisions returns empty
and DB stays at 0 bytes after hours of paper trading.

These tests pin the desired behavior so the fix can be measured.
"""
import asyncio
import json
from pathlib import Path

import pytest

from vibe_trading.web.journal_storage import DecisionJournalStorage


# === DecisionJournalStorage unit tests (the existing, untested plumbing) ===

class TestDecisionJournalStorage:
    async def test_init_creates_schema(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()
        assert db_path.exists()
        assert db_path.stat().st_size > 0

    async def test_upsert_bar_creates_row(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        await storage.upsert_bar(
            symbol="BTCUSDT",
            interval="30m",
            open_time_ms=1700000000000,
            bar_time="2024-01-01T00:00:00",
            update={"kline": {"close": 42000.0}},
        )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar is not None
        assert bar.symbol == "BTCUSDT"
        assert bar.kline == {"close": 42000.0}

    async def test_upsert_bar_persists_decision(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        decision = {
            "action": "BUY",
            "confidence": 0.9,
            "rationale": "Bullish divergence confirmed",
            "entry_price": 63000.0,
            "stop_loss": 62200.0,
            "take_profit": 64500.0,
        }

        await storage.upsert_bar(
            symbol="BTCUSDT",
            interval="30m",
            open_time_ms=1700000000000,
            bar_time="2024-01-01T00:00:00",
            update={"decision": decision},
        )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar.decision == decision

    async def test_upsert_bar_persists_report_under_phase(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        await storage.upsert_bar(
            symbol="BTCUSDT",
            interval="30m",
            open_time_ms=1700000000000,
            bar_time="2024-01-01T00:00:00",
            update={"report": {"phase": "analysts", "agent": "macro", "content": "Bullish"}},
        )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar.reports["analysts"]["macro"] == "Bullish"

    async def test_upsert_bar_accumulates_reports(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        for agent, content in [("macro", "Bullish"), ("technical", "Range-bound"), ("sentiment", "Greed 70")]:
            await storage.upsert_bar(
                symbol="BTCUSDT",
                interval="30m",
                open_time_ms=1700000000000,
                bar_time="2024-01-01T00:00:00",
                update={"report": {"phase": "analysts", "agent": agent, "content": content}},
            )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar.reports["analysts"]["macro"] == "Bullish"
        assert bar.reports["analysts"]["technical"] == "Range-bound"
        assert bar.reports["analysts"]["sentiment"] == "Greed 70"

    async def test_upsert_bar_appends_logs_capped(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        # Storage caps logs at 120 per bar
        for i in range(150):
            await storage.upsert_bar(
                symbol="BTCUSDT",
                interval="30m",
                open_time_ms=1700000000000,
                bar_time="2024-01-01T00:00:00",
                update={"log": {"level": "info", "msg": f"line {i}"}},
            )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert len(bar.logs) == 120
        # Most recent logs are kept
        assert bar.logs[-1]["msg"] == "line 149"
        assert bar.logs[0]["msg"] == "line 30"

    async def test_upsert_bar_appends_executions_capped(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        for i in range(50):
            await storage.upsert_bar(
                symbol="BTCUSDT",
                interval="30m",
                open_time_ms=1700000000000,
                bar_time="2024-01-01T00:00:00",
                update={"execution": {"order_id": f"o{i}", "price": 63000.0 + i}},
            )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert len(bar.executions) == 40  # cap at 40
        assert bar.executions[-1]["order_id"] == "o49"

    async def test_upsert_bar_unique_key(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        # Same bar updated twice — should not create duplicate rows
        await storage.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000,
            bar_time="2024-01-01T00:00:00",
            update={"kline": {"close": 42000.0}},
        )
        await storage.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000,
            bar_time="2024-01-01T00:00:00",
            update={"kline": {"close": 42500.0}},
        )

        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar.kline["close"] == 42500.0  # latest overwrites

    async def test_get_bar_nonexistent_returns_none(self, tmp_path: Path):
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        bar = await storage.get_bar(
            symbol="ETHUSDT", interval="30m", open_time_ms=9999
        )
        assert bar is None


# === Regression test: the actual bug -- coordinator never writes ===

class TestCoordinatorWritesToJournal:
    """The persistence bridge is missing. These tests reproduce the gap.

    Today: TradingCoordinator.analyze_and_decide completes but
    journal_storage never sees a row. Tomorrow: it should.
    """

    async def test_quality_tracker_record_decision_writes_to_db(self, tmp_path: Path):
        """When QualityTracker.record_decision is called with enable_persistence=True,
        there should be a write — but today _persist_decision is `pass`."""
        from vibe_trading.coordinator.quality_tracker import DecisionQualityTracker
        from vibe_trading.coordinator.signal_processor import ProcessedSignal, TradingSignal, SignalStrength

        # Arrange: tmpdir DB
        db_path = tmp_path / "decisions.db"
        storage = DecisionJournalStorage(f"sqlite:///{db_path}")
        await storage.init()

        # Inject storage into a tracker
        tracker = DecisionQualityTracker(
            storage_path=":memory:",  # tracker sqlite ignored for now
            enable_persistence=True,
        )
        # Wire journal_storage to tracker (post-fix)
        tracker._journal_storage = storage

        # Act: record a decision
        signal = ProcessedSignal(
            signal=TradingSignal.BUY,
            strength=SignalStrength.STRONG,
            confidence=0.85,
            reasoning="Bullish divergence confirmed in 4h timeframe",
            key_factors=["OI rising", "Fear index 25", "MACD cross"],
        )
        await tracker.record_decision(
            decision_id="BTCUSDT_1700000000000",
            symbol="BTCUSDT",
            signal=signal,
            agent_contributions={"pm_agent": 0.5, "risk_agent": 0.3},
            market_condition="trending",
        )

        # Assert: at least one bar in the journal with the decision recorded
        bar = await storage.get_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1700000000000
        )
        assert bar is not None, (
            "QualityTracker.record_decision should write to journal_storage. "
            "Today _persist_decision is `pass` so this test fails."
        )
        assert bar.decision is not None
        assert bar.decision["action"] in ("BUY", "SELL", "HOLD")
