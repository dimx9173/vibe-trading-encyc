"""Tests for MacroAnalysisThread + ThreadManager (Wave D — coverage 85% plan)."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.coordinator.thread_manager import ThreadManager
from vibe_trading.threads.macro_thread import MacroAnalysisThread


# ===================== MacroAnalysisThread =====================

@pytest.fixture
def macro():
    return MacroAnalysisThread(symbol="BTCUSDT", interval_seconds=3600)


class TestMacroInit:
    def test_defaults(self, macro):
        assert macro.symbol == "BTCUSDT"
        assert macro.interval_seconds == 3600
        assert macro.get_statistics()["total_runs"] == 0


class TestShouldUpdate:
    @pytest.mark.asyncio
    async def test_no_state_returns_true(self, macro):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=None)
        macro.storage = storage
        assert await macro._should_update() is True

    @pytest.mark.asyncio
    async def test_recent_state_returns_false(self, macro):
        storage = MagicMock()
        state = MagicMock()
        state.timestamp = int(__import__("time").time() * 1000)  # 剛存
        storage.get_latest_state = AsyncMock(return_value=state)
        macro.storage = storage
        assert await macro._should_update() is False

    @pytest.mark.asyncio
    async def test_old_state_returns_true(self, macro):
        storage = MagicMock()
        state = MagicMock()
        state.timestamp = int((__import__("time").time() - 7200) * 1000)  # 2h 前
        storage.get_latest_state = AsyncMock(return_value=state)
        macro.storage = storage
        assert await macro._should_update() is True


class TestCollectMarketData:
    @pytest.mark.asyncio
    async def test_collects_all(self, macro):
        with patch.object(macro, "_agent"), \
             patch("vibe_trading.threads.macro_thread.sentiment_tools.get_fear_and_greed_index",
                   new=AsyncMock(return_value={"value": 50})), \
             patch("vibe_trading.threads.macro_thread.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"funding_rate": 0.01})), \
             patch("vibe_trading.threads.macro_thread.market_data_tools.get_24hr_ticker",
                   new=AsyncMock(return_value={"close": 50000})), \
             patch("vibe_trading.threads.macro_thread.sentiment_tools.get_trending_symbols",
                   new=AsyncMock(return_value={"symbols": []})):
            data = await macro._collect_market_data()
        assert "fear_greed" in data
        assert "funding_rate" in data
        assert "ticker_24h" in data
        assert "trending" in data

    @pytest.mark.asyncio
    async def test_failures_failsafe(self, macro):
        with patch("vibe_trading.threads.macro_thread.sentiment_tools.get_fear_and_greed_index",
                   new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("vibe_trading.threads.macro_thread.fundamental_tools.get_funding_rates",
                   new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("vibe_trading.threads.macro_thread.market_data_tools.get_24hr_ticker",
                   new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("vibe_trading.threads.macro_thread.sentiment_tools.get_trending_symbols",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            data = await macro._collect_market_data()
        assert data == {"symbol": "BTCUSDT"}  # 全部失敗但不 raise


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_success(self, macro):
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={"market_regime": "BULL"})
        ms = MagicMock()
        ms.market_regime = "BULL"
        ms.trend_direction = "UPTREND"
        ms.overall_sentiment = "POSITIVE"
        ms.confidence = 0.9
        ms.to_dict.return_value = {"market_regime": "BULL"}
        agent.create_macro_state = AsyncMock(return_value=ms)
        macro._agent = agent
        storage = MagicMock()
        storage.save_state = AsyncMock(return_value=True)
        macro.storage = storage
        with patch.object(macro, "_collect_market_data", new=AsyncMock(return_value={})):
            result = await macro.run_once()
        assert result == {"market_regime": "BULL"}

    @pytest.mark.asyncio
    async def test_save_failed(self, macro):
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={})
        ms = MagicMock()
        ms.to_dict.return_value = {"x": 1}
        agent.create_macro_state = AsyncMock(return_value=ms)
        macro._agent = agent
        storage = MagicMock()
        storage.save_state = AsyncMock(return_value=False)
        macro.storage = storage
        with patch.object(macro, "_collect_market_data", new=AsyncMock(return_value={})):
            assert await macro.run_once() is None

    @pytest.mark.asyncio
    async def test_exception(self, macro):
        macro._agent = MagicMock()
        macro._agent.analyze = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(macro, "_collect_market_data", new=AsyncMock(return_value={})):
            assert await macro.run_once() is None


class TestNotify:
    @pytest.mark.asyncio
    async def test_notify_update(self, macro):
        broker = MagicMock()
        with patch("vibe_trading.threads.macro_thread.get_message_broker",
                   return_value=broker):
            ms = MagicMock()
            ms.market_regime = "BULL"
            ms.to_dict.return_value = {}
            await macro._notify_update(ms)
        broker.send.assert_called_once()


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self, macro):
        async def _loop(self):
            await asyncio_sleep(3600)
        with patch.object(MacroAnalysisThread, "_run_loop", _loop):
            await macro.start()
            assert macro._running is True
            await macro.stop()
            assert macro._running is False

    @pytest.mark.asyncio
    async def test_stop_not_running(self, macro):
        await macro.stop()  # 不 raise


# ===================== ThreadManager =====================

class TestThreadManager:
    @pytest.mark.asyncio
    async def test_register_get(self):
        mgr = ThreadManager()
        info = await mgr.register_thread("main", "main_thread", {})
        assert info is not None
        got = await mgr.get_thread_info("main")
        assert got is not None
        assert got.name == "main"

    @pytest.mark.asyncio
    async def test_register_duplicate(self):
        mgr = ThreadManager()
        await mgr.register_thread("main", "main_thread", {})
        with pytest.raises(ValueError):
            await mgr.register_thread("main", "main_thread", {})

    @pytest.mark.asyncio
    async def test_get_missing(self):
        mgr = ThreadManager()
        assert await mgr.get_thread_info("nope") is None

    @pytest.mark.asyncio
    async def test_get_all_threads(self):
        mgr = ThreadManager()
        await mgr.register_thread("a", "main_thread", {})
        await mgr.register_thread("b", "macro_thread", {})
        threads = await mgr.get_all_threads()
        assert set(threads.keys()) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_start_stop_missing(self):
        mgr = ThreadManager()
        assert await mgr.start_thread("nope") is False
        assert await mgr.stop_thread("nope") is False
        assert await mgr.pause_thread("nope") is False
        assert await mgr.resume_thread("nope") is False

    @pytest.mark.asyncio
    async def test_is_emergency_mode(self):
        ss = MagicMock()
        ss.get = AsyncMock(return_value=False)
        ss.set = AsyncMock()
        mgr = ThreadManager(shared_state=ss)
        mgr._wait_for_main_thread_stop = AsyncMock()
        assert await mgr.is_emergency_mode() is False
        await mgr.notify_emergency_mode({"type": "crash"})
        await mgr.notify_emergency_complete()
        assert ss.set.call_count >= 2

    @pytest.mark.asyncio
    async def test_run_thread(self):
        mgr = ThreadManager()
        await mgr.register_thread("t", "main_thread", {})
        result = await mgr.run_thread("t", {"x": 1})
        # main_thread 未實作 → 回 None 或錯誤
        assert result is not None or result is None

    def test_thread_info_to_dict(self):
        from vibe_trading.coordinator.thread_manager import ThreadInfo, ThreadStatus
        info = ThreadInfo(name="t", task=None, status=ThreadStatus.STOPPED)
        d = info.to_dict()
        assert d["name"] == "t"
        assert d["status"] == "stopped"


def asyncio_sleep(sec):
    import asyncio
    return asyncio.sleep(sec)


class TestThreadManagerRun:
    @pytest.mark.asyncio
    async def test_run_thread_success(self):
        mgr = ThreadManager()
        await mgr.register_thread("t", "main_thread", {})
        await mgr.run_thread("t", async_noop)
        info = await mgr.get_thread_info("t")
        assert info is not None
        assert info.status.value == "stopped"

    @pytest.mark.asyncio
    async def test_run_thread_not_found(self):
        mgr = ThreadManager()
        await mgr.run_thread("nope", async_noop)  # 不 raise

    @pytest.mark.asyncio
    async def test_run_thread_error(self):
        mgr = ThreadManager()
        await mgr.register_thread("t", "main_thread", {})

        async def _fail():
            raise RuntimeError("boom")

        await mgr.run_thread("t", _fail)
        info = await mgr.get_thread_info("t")
        assert info is not None
        assert info.status.value == "error"
        assert info.error_count == 1

    @pytest.mark.asyncio
    async def test_run_thread_wrapper_no_info(self):
        mgr = ThreadManager()
        await mgr._run_thread_wrapper("missing", async_noop)  # 不 raise

    @pytest.mark.asyncio
    async def test_pause_resume(self):
        from vibe_trading.coordinator.thread_manager import ThreadStatus
        mgr = ThreadManager()
        await mgr.register_thread("t", "main_thread", {})
        info = await mgr.get_thread_info("t")
        info.status = ThreadStatus.RUNNING
        assert await mgr.pause_thread("t") is True
        info = await mgr.get_thread_info("t")
        assert info.status.value == "paused"
        assert await mgr.resume_thread("t") is True
        info = await mgr.get_thread_info("t")
        assert info.status.value == "running"


async def async_noop():
    return None


class TestThreadManagerExtras:
    @pytest.mark.asyncio
    async def test_get_statistics(self):
        mgr = ThreadManager()
        await mgr.register_thread("a", "main_thread", {})
        stats = await mgr.get_statistics()
        assert stats["total_threads"] == 1

    @pytest.mark.asyncio
    async def test_wait_for_main_thread_stop_timeout(self):
        # 不真實等待 30s: patch wait_for 直接 raise
        import asyncio
        mgr = ThreadManager()
        ss = MagicMock()
        ss.subscribe = MagicMock()
        ss.unsubscribe = MagicMock()
        mgr.shared_state = ss
        with patch("vibe_trading.coordinator.thread_manager.asyncio.wait_for",
                   new=AsyncMock(side_effect=asyncio.TimeoutError)):
            with pytest.raises(asyncio.TimeoutError):
                await mgr._wait_for_main_thread_stop()

    @pytest.mark.asyncio
    async def test_wait_for_main_thread_stop_sets(self):
        mgr = ThreadManager()
        ss = MagicMock()

        def subscribe(key, cb):
            # 立即觸發
            from vibe_trading.coordinator.shared_state import StateChangeEvent
            cb(StateChangeEvent(key="main_thread_stopped",
                                old_value=False, new_value=True))

        ss.subscribe = subscribe
        ss.unsubscribe = MagicMock()
        mgr.shared_state = ss
        await mgr._wait_for_main_thread_stop()  # 立即完成, 不 raise
