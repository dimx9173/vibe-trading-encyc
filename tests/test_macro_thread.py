"""Tests for MacroAnalysisThread — Wave D113."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.threads.macro_thread import MacroAnalysisThread


def _thread(storage=None, agent=None):
    t = MacroAnalysisThread.__new__(MacroAnalysisThread)
    t.symbol = "BTCUSDT"
    t.interval_seconds = 3600
    t.storage = storage or MagicMock()
    t._agent = agent or MagicMock()
    t._tool_context = MagicMock()
    t._running = False
    t._task = None
    t._total_runs = 0
    t._successful_runs = 0
    t._failed_runs = 0
    t._last_run_time = None
    return t


class TestMacroThread:
    @pytest.mark.asyncio
    async def test_initialize(self):
        t = _thread()
        t.storage.init = AsyncMock(return_value=None)
        agent = MagicMock()
        agent.initialize = AsyncMock()
        with pytest.importorskip("unittest.mock").patch(
            "vibe_trading.threads.macro_thread.MacroAnalysisAgent",
            return_value=agent):
            await t.initialize()
        assert t._agent is agent
        assert t._tool_context is not None

    @pytest.mark.asyncio
    async def test_start_stop(self):
        t = _thread()
        t._run_loop = AsyncMock()
        await t.start()
        assert t._running is True
        assert t._task is not None
        await t.start()  # 已 running → warning
        await t.stop()
        assert t._running is False

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        t = _thread()
        await t.stop()  # 不 raise

    @pytest.mark.asyncio
    async def test_should_update_no_state(self):
        t = _thread()
        t.storage.get_latest_state = AsyncMock(return_value=None)
        assert await t._should_update() is True

    @pytest.mark.asyncio
    async def test_should_update_fresh(self):
        import time
        t = _thread()
        state = MagicMock()
        state.timestamp = int(time.time() * 1000)  # 剛更新
        t.storage.get_latest_state = AsyncMock(return_value=state)
        assert await t._should_update() is False

    @pytest.mark.asyncio
    async def test_run_analysis_success(self):
        t = _thread()
        t._collect_market_data = AsyncMock(return_value={"symbol": "BTCUSDT"})
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={"regime": "bull"})
        state = MagicMock()
        state.market_regime = "bull"
        state.trend_direction = "up"
        state.overall_sentiment = "positive"
        state.confidence = 0.8
        agent.create_macro_state = AsyncMock(return_value=state)
        t._agent = agent
        t.storage.save_state = AsyncMock(return_value=True)
        t._notify_update = AsyncMock()
        await t._run_analysis()
        assert t._total_runs == 1
        assert t._successful_runs == 1
        t._notify_update.assert_called_once_with(state)

    @pytest.mark.asyncio
    async def test_run_analysis_save_fail(self):
        t = _thread()
        t._collect_market_data = AsyncMock(return_value={})
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={})
        agent.create_macro_state = AsyncMock(return_value=MagicMock())
        t._agent = agent
        t.storage.save_state = AsyncMock(return_value=False)
        await t._run_analysis()
        assert t._failed_runs == 1

    @pytest.mark.asyncio
    async def test_run_analysis_error(self):
        t = _thread()
        t._collect_market_data = AsyncMock(
            side_effect=RuntimeError("boom"))
        t._agent.analyze = AsyncMock()
        await t._run_analysis()
        assert t._failed_runs == 1

    @pytest.mark.asyncio
    async def test_collect_market_data_partial_failure(self):
        from vibe_trading.threads import macro_thread as mt
        t = _thread()
        t._agent = MagicMock()
        with pytest.importorskip("unittest.mock").patch.object(
            mt.sentiment_tools, "get_fear_and_greed_index",
            new=AsyncMock(side_effect=RuntimeError("down"))), \
            pytest.importorskip("unittest.mock").patch.object(
                mt.fundamental_tools, "get_funding_rates",
                new=AsyncMock(return_value={"rate": 0.01})), \
            pytest.importorskip("unittest.mock").patch.object(
                mt.market_data_tools, "get_24hr_ticker",
                new=AsyncMock(return_value={"price": 1.0})), \
            pytest.importorskip("unittest.mock").patch.object(
                mt.sentiment_tools, "get_trending_symbols",
                new=AsyncMock(return_value=[])):
            data = await t._collect_market_data()
        assert "fear_greed" not in data  # 失敗被跳過
        assert data["funding_rate"]["rate"] == 0.01
        assert data["ticker_24h"]["price"] == 1.0

    @pytest.mark.asyncio
    async def test_notify_update(self):
        from vibe_trading.threads import macro_thread as mt
        t = _thread()
        state = MagicMock()
        state.to_dict = MagicMock(return_value={"regime": "bull"})
        broker = MagicMock()
        with pytest.importorskip("unittest.mock").patch.object(
            mt, "get_message_broker", return_value=broker):
            await t._notify_update(state)
        broker.send.assert_called_once()
        assert broker.send.call_args.kwargs["receiver"] == "all"

    def test_get_statistics(self):
        t = _thread()
        t._total_runs = 4
        t._successful_runs = 3
        stats = t.get_statistics()
        assert stats["success_rate"] == 0.75
        assert stats["running"] is False
        assert stats["last_run_time"] is None

    @pytest.mark.asyncio
    async def test_run_once_success(self):
        t = _thread()
        t._collect_market_data = AsyncMock(return_value={})
        state = MagicMock()
        state.to_dict = MagicMock(return_value={"regime": "bull"})
        t._agent.analyze = AsyncMock(return_value={})
        t._agent.create_macro_state = AsyncMock(return_value=state)
        t.storage.save_state = AsyncMock(return_value=True)
        result = await t.run_once()
        assert result == {"regime": "bull"}

    @pytest.mark.asyncio
    async def test_run_once_save_fail(self):
        t = _thread()
        t._collect_market_data = AsyncMock(return_value={})
        t._agent.analyze = AsyncMock(return_value={})
        t._agent.create_macro_state = AsyncMock(return_value=MagicMock())
        t.storage.save_state = AsyncMock(return_value=False)
        assert await t.run_once() is None

    @pytest.mark.asyncio
    async def test_run_once_error(self):
        t = _thread()
        t._collect_market_data = AsyncMock(
            side_effect=RuntimeError("boom"))
        assert await t.run_once() is None
