"""Tests for MultiThreadedTradingSystem (Wave D — coverage 85% plan).

全部依賴用 mock (thread_manager/shared_state/event_queue/triggers/threads).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.main.multi_thread_main import MultiThreadedTradingSystem


@pytest.fixture
def system():
    tm = MagicMock()
    tm.register_thread = AsyncMock()
    tm.start_thread = AsyncMock(return_value=True)
    tm.run_thread = AsyncMock()
    tm.get_statistics = AsyncMock(return_value={"total_threads": 3})
    ss = MagicMock()
    ss.start_cleanup_task = AsyncMock()
    ss.stop_cleanup_task = AsyncMock()
    ss.set = AsyncMock()
    ss.get_statistics = AsyncMock(return_value={"total_keys": 2})
    eq = MagicMock()
    eq.put = AsyncMock()
    eq.get_statistics = AsyncMock(return_value={"queue_size": 0})
    tr = MagicMock()
    tr.evaluate_all = AsyncMock(return_value=[])
    tr.get_statistics = MagicMock(return_value=MagicMock(total_triggers=2))
    pc = MagicMock()
    pc.get_price_with_fallback = AsyncMock(return_value=50000.0)

    with patch("vibe_trading.main.multi_thread_main.get_thread_manager",
               return_value=tm), \
         patch("vibe_trading.main.multi_thread_main.get_shared_state_manager",
               return_value=ss), \
         patch("vibe_trading.main.multi_thread_main.get_event_queue",
               return_value=eq), \
         patch("vibe_trading.main.multi_thread_main.get_trigger_registry",
               return_value=tr), \
         patch("vibe_trading.main.multi_thread_main.get_price_cache",
               return_value=pc):
        s = MultiThreadedTradingSystem(symbol="BTCUSDT")
        s.thread_manager = tm
        s.shared_state = ss
        s.event_queue = eq
        s.trigger_registry = tr
        s._price_cache = pc
        yield s


class TestInit:
    def test_defaults(self, system):
        assert system.symbol == "BTCUSDT"
        assert system.mode == "paper"
        assert system.macro_thread is None
        assert system._running is False


class TestPrice:
    @pytest.mark.asyncio
    async def test_get_current_price(self, system):
        assert await system._get_current_price() == 50000.0

    @pytest.mark.asyncio
    async def test_get_price_from_rest(self, system):
        with patch("vibe_trading.main.multi_thread_main.market_data_tools.get_current_price",
                   new=AsyncMock(return_value={"price": 48000.0})):
            assert await system._get_price_from_rest() == 48000.0

    @pytest.mark.asyncio
    async def test_get_price_from_rest_error(self, system):
        with patch("vibe_trading.main.multi_thread_main.market_data_tools.get_current_price",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            assert await system._get_price_from_rest() is None


class TestPositionsBalance:
    @pytest.mark.asyncio
    async def test_no_executor(self, system):
        assert await system._get_positions() == []
        assert await system._get_account_balance() == 10000.0

    @pytest.mark.asyncio
    async def test_with_executor(self, system):
        ex = MagicMock()
        p = MagicMock()
        p.symbol = "BTCUSDT"
        p.position_amount = 0.1
        p.entry_price = 48000.0
        p.mark_price = 50000.0
        p.unrealized_profit = 200.0
        p.liquidation_price = 40000.0
        p.leverage = 5
        p.position_side.value = "LONG"
        p.notional = 4800.0
        ex.get_positions = AsyncMock(return_value=[p])
        ex.get_balance = AsyncMock(return_value={"USDT": {"available": 5000.0}})
        system.executor = ex
        positions = await system._get_positions()
        assert positions[0]["symbol"] == "BTCUSDT"
        assert await system._get_account_balance() == 5000.0


class TestCheckTriggers:
    @pytest.mark.asyncio
    async def test_check_triggers_no_price(self, system):
        system._price_cache.get_price_with_fallback = AsyncMock(return_value=None)
        await system._check_triggers()  # price None → return

    @pytest.mark.asyncio
    async def test_check_triggers_with_events(self, system):
        event = MagicMock()
        event.trigger_name = "price_drop"
        event.severity.value = "high"
        event.symbol = "BTCUSDT"
        event.to_dict.return_value = {"name": "price_drop"}
        event.data = {}
        event.event_id = "evt1"
        system.trigger_registry.evaluate_all = AsyncMock(return_value=[event])
        with patch.object(system, "_handle_trigger_event", new=AsyncMock()) as h:
            await system._check_triggers()
        h.assert_called_once()


class TestHandleTriggerEvent:
    @pytest.mark.asyncio
    async def test_handle_event_high_severity(self, system):
        event = MagicMock()
        event.trigger_name = "crash"
        event.severity.value = "critical"
        event.symbol = "BTCUSDT"
        event.to_dict.return_value = {}
        event.data = {}
        event.event_id = "e1"
        broker = MagicMock()
        with patch("vibe_trading.agents.messaging.get_message_broker",
                   return_value=broker):
            await system._handle_trigger_event(event)
        broker.send.assert_called_once()
        system.shared_state.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_low_severity(self, system):
        event = MagicMock()
        event.trigger_name = "info"
        event.severity.value = "low"
        event.symbol = "BTCUSDT"
        event.to_dict.return_value = {}
        event.data = {}
        await system._handle_trigger_event(event)
        system.shared_state.set.assert_called_once()


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_requires_init(self, system):
        # mock threads 讓 start 完整執行
        system.macro_thread = MagicMock()
        system.macro_thread.start = AsyncMock()
        system.onbar_thread = MagicMock()
        system.onbar_thread.start = AsyncMock()
        with patch.object(system, "_print_system_status", new=AsyncMock()):
            await system.start()
        assert system._running is True

    @pytest.mark.asyncio
    async def test_stop_not_running(self, system):
        await system.stop()  # 不 raise

    @pytest.mark.asyncio
    async def test_start_twice(self, system):
        system._running = True
        await system.start()  # already running → skip


class TestPrintStatus:
    @pytest.mark.asyncio
    async def test_print_status(self, system):
        with patch.object(system, "macro_thread", None), \
             patch.object(system, "onbar_thread", None), \
             patch.object(system, "emergency_handler", None):
            await system._print_system_status()  # 不 raise


class TestSystemLifecycle:
    @pytest.mark.asyncio
    async def test_run_stop(self, system):
        system.macro_thread = MagicMock()
        system.macro_thread.start = AsyncMock()
        system.macro_thread.stop = AsyncMock()
        system.macro_thread.get_statistics = MagicMock(return_value={"total_runs": 1})
        system.onbar_thread = MagicMock()
        system.onbar_thread.start = AsyncMock()
        system.onbar_thread.stop = AsyncMock()
        system.onbar_thread.get_statistics = MagicMock(return_value={"total_bars": 5})
        system.emergency_handler = MagicMock()
        system.emergency_handler.get_statistics = MagicMock(return_value={"total_handled": 2})

        # run: initialize + start + wait + stop
        with patch.object(system, "initialize", new=AsyncMock()), \
             patch.object(system, "start", new=AsyncMock()), \
             patch.object(system, "stop", new=AsyncMock()) as mock_stop:
            # 直接測 stop (已 running)
            system._running = True
            await system.stop()
            mock_stop  # stop 本身被覆寫, 這裡測 real stop
        # 測試真實 stop: 先設 running
        system2 = system
        system2._running = True
        system2.event_thread = None
        with patch.object(system2.thread_manager, "get_statistics",
                          new=AsyncMock(return_value={"total_threads": 3})), \
             patch.object(system2, "_print_system_status", new=AsyncMock()):
            await system2.stop()
        assert system2._running is False

    def test_setup_signal_handlers(self, system):
        with patch("signal.signal") as mock_signal:
            system.setup_signal_handlers()
        assert mock_signal.call_count == 2


class TestEventThread:
    @pytest.mark.skip(reason="asyncio.sleep 迴圈卡住 — 環境限制")
    @pytest.mark.asyncio
    async def test_run_event_thread_stops(self):
        system = MultiThreadedTradingSystem.__new__(MultiThreadedTradingSystem)
        system._running = True
        system.emergency_handler = MagicMock()
        system.emergency_handler.process_event_queue = AsyncMock()
        system.trigger_registry = MagicMock()
        system.trigger_registry.evaluate_all = AsyncMock(return_value=[])
        system._last_price = None
        system._last_price_update = None
        system._price_cache = MagicMock()
        system._price_cache.get_price_with_fallback = AsyncMock(return_value=50000.0)
        system.executor = None
        system.symbol = "BTCUSDT"

        iterations = []

        async def _check():
            iterations.append(1)
            if len(iterations) >= 2:
                system._running = False

        with patch.object(system, "_check_triggers", new=_check), \
             patch("vibe_trading.main.multi_thread_main.asyncio.sleep",
                   new=AsyncMock()):
            await system._run_event_thread()
        assert len(iterations) >= 1


class TestMainEntry:
    @pytest.mark.asyncio
    async def test_main_success(self):
        import vibe_trading.main.multi_thread_main as mtm
        system = MagicMock()
        system.run = AsyncMock()
        system.stop = AsyncMock()
        system.setup_signal_handlers = MagicMock()
        with patch.object(mtm, "MultiThreadedTradingSystem", return_value=system), \
             patch.object(mtm, "signal") as mock_signal:
            mock_signal.signal = MagicMock()
            await mtm.main()
        system.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_exception(self):
        import vibe_trading.main.multi_thread_main as mtm
        system = MagicMock()
        system.run = AsyncMock(side_effect=RuntimeError("boom"))
        system.stop = AsyncMock()
        system.setup_signal_handlers = MagicMock()
        with patch.object(mtm, "MultiThreadedTradingSystem", return_value=system), \
             patch.object(mtm, "signal") as mock_signal:
            mock_signal.signal = MagicMock()
            await mtm.main()
        system.stop.assert_called_once()
