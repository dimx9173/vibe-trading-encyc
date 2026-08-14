"""
Tests for P1-1: Checkpoint/Resume functionality

Verifies that:
1. Checkpoints are saved after each phase completes
2. resume_from_checkpoint() can restore state and continue execution
3. Resumed execution skips already-completed phases
4. Checkpoint data is complete and correct
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.data_sources.checkpoint_storage import DecisionCheckpointStore
from vibe_trading.data_sources.kline_storage import KlineStorage
from vibe_trading.execution.order_executor import PaperOrderExecutor


@pytest.fixture
def mock_storage():
    """Mock KlineStorage"""
    storage = MagicMock(spec=KlineStorage)
    storage.get_klines = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def mock_executor():
    """Mock PaperOrderExecutor"""
    executor = MagicMock(spec=PaperOrderExecutor)
    executor.get_balance = AsyncMock(return_value={"USDT": {"balance": 10000.0}})
    executor.get_positions = AsyncMock(return_value=[])
    return executor


@pytest.fixture
def coordinator(mock_storage, mock_executor):
    """Create TradingCoordinator with mocked dependencies"""
    return TradingCoordinator(
        symbol="BTCUSDT",
        interval="30m",
        storage=mock_storage,
        executor=mock_executor,
    )


@pytest.fixture
def checkpoint_store():
    """Create a fresh checkpoint store for testing"""
    return DecisionCheckpointStore(db_path=":memory:")


def _mock_context():
    """Return a mock context dict for _prepare_context"""
    return {
        "symbol": "BTCUSDT",
        "interval": "30m",
        "current_price": 50000.0,
        "klines": [],
        "indicators": {},
        "market_data": {},
        "timestamp": 1234567890,
    }


class TestCheckpointStorage:
    """Test checkpoint storage functionality"""

    def test_save_checkpoint(self, checkpoint_store):
        """Test saving a checkpoint"""
        decision_id = "test_decision_1"
        context = {
            "analyst_reports": {"technical": "report1"},
            "current_price": 50000.0,
        }

        checkpoint_id = checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="analyzing",
            context=context,
        )

        assert checkpoint_id > 0

    def test_get_latest_checkpoint(self, checkpoint_store):
        """Test retrieving the latest checkpoint"""
        decision_id = "test_decision_2"

        # Save multiple checkpoints
        checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="analyzing",
            context={"phase": 1},
        )

        checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="debating",
            context={"phase": 2},
        )

        # Get latest should return the second one
        checkpoint = checkpoint_store.get_latest_checkpoint(decision_id)

        assert checkpoint is not None
        assert checkpoint["completed_phase"] == "debating"
        assert checkpoint["context"]["phase"] == 2

    def test_get_latest_checkpoint_not_found(self, checkpoint_store):
        """Test retrieving non-existent checkpoint"""
        checkpoint = checkpoint_store.get_latest_checkpoint("non_existent")
        assert checkpoint is None

    def test_checkpoint_context_completeness(self, checkpoint_store):
        """Test that checkpoint contains all required context"""
        decision_id = "test_decision_3"
        context = {
            "analyst_reports": {"technical": "report1", "fundamental": "report2"},
            "investment_plan": "plan1",
            "risk_assessment": {"risk": "low"},
            "trading_plan": {"action": "buy"},
            "final_decision": {"decision": "BUY"},
            "current_price": 50000.0,
            "account_balance": 10000.0,
            "current_positions": [],
        }

        checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="completed",
            context=context,
        )

        checkpoint = checkpoint_store.get_latest_checkpoint(decision_id)

        # Verify all context fields are preserved
        assert checkpoint["context"]["analyst_reports"] == context["analyst_reports"]
        assert checkpoint["context"]["investment_plan"] == context["investment_plan"]
        assert checkpoint["context"]["risk_assessment"] == context["risk_assessment"]
        assert checkpoint["context"]["trading_plan"] == context["trading_plan"]
        assert checkpoint["context"]["final_decision"] == context["final_decision"]
        assert checkpoint["context"]["current_price"] == context["current_price"]
        assert checkpoint["context"]["account_balance"] == context["account_balance"]
        assert checkpoint["context"]["current_positions"] == context["current_positions"]


class TestCheckpointIntegration:
    """Test checkpoint integration with TradingCoordinator"""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_after_phase1(self, coordinator):
        """Test that checkpoint is saved after Phase 1 (analyzing) completes"""
        with patch.object(coordinator, '_prepare_context', new_callable=AsyncMock) as mock_prepare:
            mock_prepare.return_value = _mock_context()

            with patch.object(coordinator, '_run_analysts_parallel', new_callable=AsyncMock) as mock_analysts:
                mock_analysts.return_value = {"technical": "report1"}

                with patch.object(coordinator, '_run_research_debate', new_callable=AsyncMock) as mock_research:
                    mock_research.return_value = "investment plan"

                    with patch.object(coordinator, '_run_risk_assessment', new_callable=AsyncMock) as mock_risk:
                        mock_risk.return_value = {"risk": "low"}

                        with patch.object(coordinator, '_run_trader', new_callable=AsyncMock) as mock_trader:
                            mock_trader.return_value = {"action": "buy"}

                            with patch.object(coordinator, '_run_portfolio_manager', new_callable=AsyncMock) as mock_pm:
                                mock_pm.return_value = {"decision": "BUY", "rationale": "test", "confidence": 0.8}

                                await coordinator.analyze_and_decide(
                                    current_price=50000.0,
                                    account_balance=10000.0,
                                    current_positions=[],
                                    bar_open_time_ms=1234567890,
                                )

        # Check that checkpoint was saved
        checkpoints = coordinator._checkpoint_store.get_all_checkpoints()
        assert len(checkpoints) > 0

        # Find the checkpoint for this decision
        phase1_checkpoint = None
        for cp in checkpoints:
            if cp["completed_phase"] == "analyzing":
                phase1_checkpoint = cp
                break

        assert phase1_checkpoint is not None
        assert "analyst_reports" in phase1_checkpoint["context"]

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, coordinator):
        """Test resuming from a checkpoint"""
        decision_id = "test_resume_decision"

        # Manually save a checkpoint
        coordinator._checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="analyzing",
            context={
                "analyst_reports": {"technical": "report1"},
                "current_price": 50000.0,
                "account_balance": 10000.0,
                "current_positions": [],
            },
        )

        with patch.object(coordinator, '_prepare_context', new_callable=AsyncMock) as mock_prepare:
            mock_prepare.return_value = _mock_context()

            with patch.object(coordinator, '_run_research_debate', new_callable=AsyncMock) as mock_debate:
                mock_debate.return_value = "investment_plan_1"

                with patch.object(coordinator, '_run_risk_assessment', new_callable=AsyncMock) as mock_risk:
                    mock_risk.return_value = {"risk": "low"}

                    with patch.object(coordinator, '_run_trader', new_callable=AsyncMock) as mock_trader:
                        mock_trader.return_value = {"action": "buy"}

                        with patch.object(coordinator, '_run_portfolio_manager', new_callable=AsyncMock) as mock_pm:
                            mock_pm.return_value = {
                                "decision": "BUY",
                                "rationale": "test rationale",
                                "confidence": 0.8,
                            }

                            # Resume from checkpoint
                            result = await coordinator.resume_from_checkpoint(
                                decision_id=decision_id,
                                current_price=50000.0,
                                account_balance=10000.0,
                                current_positions=[],
                                bar_open_time_ms=1234567890,
                            )

        # Verify result
        assert result is not None
        assert result.decision == "BUY"
        assert result.rationale == "test rationale"

        # Verify that the checkpoint was updated
        final_checkpoint = coordinator._checkpoint_store.get_latest_checkpoint(decision_id)
        assert final_checkpoint["completed_phase"] == "completed"

    @pytest.mark.asyncio
    async def test_resume_from_completed_checkpoint(self, coordinator):
        """Test resuming from an already-completed checkpoint"""
        decision_id = "test_completed_resume"

        # Save a completed checkpoint
        coordinator._checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol="BTCUSDT",
            interval="30m",
            completed_phase="completed",
            context={
                "analyst_reports": {"technical": "report1"},
                "investment_plan": "plan1",
                "risk_assessment": {"risk": "low"},
                "trading_plan": {"action": "buy"},
                "final_decision": {
                    "decision": "BUY",
                    "rationale": "original rationale",
                    "confidence": 0.9,
                },
                "current_price": 50000.0,
                "account_balance": 10000.0,
                "current_positions": [],
            },
        )

        # Resume should return immediately without executing any phases
        result = await coordinator.resume_from_checkpoint(
            decision_id=decision_id,
            current_price=50000.0,
        )

        assert result is not None
        assert result.decision == "BUY"
        assert result.rationale == "original rationale"

    @pytest.mark.asyncio
    async def test_resume_nonexistent_checkpoint(self, coordinator):
        """Test resuming from a non-existent checkpoint"""
        result = await coordinator.resume_from_checkpoint(
            decision_id="non_existent_decision",
            current_price=50000.0,
        )

        assert result is None
