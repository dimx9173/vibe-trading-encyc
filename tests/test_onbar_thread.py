"""Tests for OnBarThread (Wave C — coverage 85% plan)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.threads.onbar_thread import OnBarThread


def _kline(close: float = 50000.0) -> MagicMock:
    k = MagicMock()
    k.close = close
    k.open = close * 0.99
    k.high = close * 1.01
    k.low = close * 0.98
    k.volume = 100.0
    k.open_time = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return k


def _position(side: str = "LONG") -> MagicMock:
    p = MagicMock()
    p.symbol = "BTCUSDT"
    p.position_amount = 0.1
    p.entry_price = 48000.0
    p.mark_price = 50000.0
    p.unrealized_profit = 200.0
    p.liquidation_price = 40000.0
    p.leverage = 5
    p.position_side.value = side
    p.notional = 4800.0
    return p


def _decision(decision: str = "HOLD") -> MagicMock:
    d = MagicMock()
    d.decision = decision
    d.rationale = "Test rationale"
    d.to_dict.return_value = {"decision": decision, "rationale": d.rationale}
    return d


@pytest.fixture
def onbar():
    mgr = MagicMock()
    mgr.is_emergency_mode = AsyncMock(return_value=False)
    return OnBarThread(symbol="BTCUSDT", interval="30m", thread_manager=mgr)


class TestInit:
    def test_defaults(self, onbar):
        assert onbar.symbol == "BTCUSDT"
        assert onbar.interval == "30m"
        assert onbar._running is False
        assert onbar.get_statistics()["total_bars"] == 0

    def test_init_default_manager(self):
        with patch("vibe_trading.threads.onbar_thread.get_thread_manager"):
            t = OnBarThread(symbol="BTCUSDT")
        assert t.thread_manager is not None


class TestPositionsBalance:
    @pytest.mark.asyncio
    async def test_get_positions_no_executor(self, onbar):
        assert await onbar._get_positions() == []

    @pytest.mark.asyncio
    async def test_get_positions_with_executor(self, onbar):
        ex = MagicMock()
        ex.get_positions = AsyncMock(return_value=[_position()])
        onbar.executor = ex
        positions = await onbar._get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSDT"
        assert positions[0]["position_side"] == "LONG"

    @pytest.mark.asyncio
    async def test_get_balance_no_executor(self, onbar):
        assert await onbar._get_account_balance() == 10000.0

    @pytest.mark.asyncio
    async def test_get_balance_with_executor(self, onbar):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={"USDT": {"available": 5000.0}})
        onbar.executor = ex
        assert await onbar._get_account_balance() == 5000.0

    @pytest.mark.asyncio
    async def test_get_balance_float(self, onbar):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={"USDT": 3000.0})
        onbar.executor = ex
        assert await onbar._get_account_balance() == 3000.0


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self, onbar):
        async def _run_loop(self):
            await asyncio.sleep(3600)

        with patch.object(OnBarThread, "_run_loop", _run_loop):
            await onbar.start()
            assert onbar._running is True
            assert onbar._task is not None
            # 重複 start 不啟動第二個 task
            first_task = onbar._task
            await onbar.start()
            assert onbar._task is first_task
            await onbar.stop()
            assert onbar._running is False
            assert onbar._task is not None and onbar._task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_not_running(self, onbar):
        await onbar.stop()  # 不 raise


class TestEmergency:
    @pytest.mark.asyncio
    async def test_is_emergency_mode(self, onbar):
        assert await onbar._is_emergency_mode() is False

    @pytest.mark.asyncio
    async def test_handle_emergency_stop(self, onbar):
        msg = MagicMock()
        msg.content = {"action": "emergency_stop"}
        await onbar._handle_emergency_message(msg)
        assert onbar._emergency_mode is True

    @pytest.mark.asyncio
    async def test_handle_emergency_resume(self, onbar):
        onbar._emergency_mode = True
        msg = MagicMock()
        msg.content = {"action": "emergency_resume"}
        await onbar._handle_emergency_message(msg)
        assert onbar._emergency_mode is False

    @pytest.mark.asyncio
    async def test_handle_emergency_suggestion(self, onbar):
        msg = MagicMock()
        msg.content = {"action": "emergency_suggestion", "suggestion": "reduce"}
        await onbar._handle_emergency_message(msg)  # 不 raise


class TestProcessKline:
    @pytest.mark.asyncio
    async def test_process_kline_no_coordinator_failsafe(self, onbar):
        # coordinator None → analyze_and_decide AttributeError → except 捕獲
        with patch("vibe_trading.threads.onbar_thread.get_message_broker"):
            await onbar._process_kline(_kline())
        assert onbar._total_bars == 1

    @pytest.mark.asyncio
    async def test_process_kline_with_coordinator(self, onbar):
        coord = MagicMock()
        coord.analyze_and_decide = AsyncMock(return_value=_decision("BUY"))
        onbar._coordinator = coord
        with patch("vibe_trading.threads.onbar_thread.get_message_broker"):
            await onbar._process_kline(_kline())
        assert onbar._total_bars == 1
        assert onbar._decisions_made == 1
        coord.analyze_and_decide.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_kline_hold_decision(self, onbar):
        coord = MagicMock()
        coord.analyze_and_decide = AsyncMock(return_value=_decision("HOLD"))
        onbar._coordinator = coord
        with patch("vibe_trading.threads.onbar_thread.get_message_broker"):
            await onbar._process_kline(_kline())
        assert onbar._decisions_made == 1

    @pytest.mark.asyncio
    async def test_execute_trade_placeholder(self, onbar):
        await onbar._execute_trade(_decision("BUY"))  # 不 raise


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_run_once_success(self, onbar):
        coord = MagicMock()
        coord.analyze_and_decide = AsyncMock(return_value=_decision("HOLD"))
        onbar._coordinator = coord
        result = await onbar.run_once(50000.0)
        assert result is not None
        assert result["decision"] == "HOLD"

    @pytest.mark.asyncio
    async def test_run_once_failure(self, onbar):
        coord = MagicMock()
        coord.analyze_and_decide = AsyncMock(side_effect=RuntimeError("boom"))
        onbar._coordinator = coord
        assert await onbar.run_once(50000.0) is None


class TestStats:
    def test_statistics(self, onbar):
        onbar._total_bars = 2
        onbar._decisions_made = 1
        stats = onbar.get_statistics()
        assert stats["decision_rate"] == 0.5
        assert stats["running"] is False

    def test_statistics_zero_bars(self, onbar):
        assert onbar.get_statistics()["decision_rate"] == 0.0
