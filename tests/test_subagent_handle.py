"""Tests for SubagentHandle (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.prime.message_channel import MessageChannel

from vibe_trading.prime.subagent_handle import SubagentHandle


def _handle(channel=None, agent=None):
    return SubagentHandle(
        agent_id="analyst_1",
        agent=agent or MagicMock(),
        channel=channel or MessageChannel(enable_dedup=False),
        config=MagicMock(),
        symbol="BTCUSDT",
        interval="30m",
    )


class TestInit:
    def test_defaults(self):
        h = _handle()
        assert h.agent_id == "analyst_1"
        assert h.running is False
        assert h.messages_sent == 0
        assert h.errors_count == 0


class TestExecuteAgent:
    @pytest.mark.asyncio
    async def test_with_analyze(self):
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={"trend": "up"})
        h = _handle(agent=agent)
        with pytest.importorskip("unittest.mock").patch(
            "vibe_trading.tools.market_data_tools.get_current_price",
            new=AsyncMock(return_value={"price": 50000.0}),
        ):
            result = await h._execute_agent()
        assert result["status"] == "success"
        assert result["data"]["current_price"] == {"price": 50000.0}

    @pytest.mark.asyncio
    async def test_price_failure_failsafe(self):
        agent = MagicMock()
        agent.analyze = AsyncMock(return_value={"trend": "up"})
        h = _handle(agent=agent)
        with pytest.importorskip("unittest.mock").patch(
            "vibe_trading.tools.market_data_tools.get_current_price",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            result = await h._execute_agent()
        assert result["status"] == "success"
        assert result["data"]["current_price"] is None

    @pytest.mark.asyncio
    async def test_no_analyze_method(self):
        agent = object()  # 無 analyze
        h = _handle(agent=agent)
        result = await h._execute_agent()
        assert result["status"] == "success"
        assert "is running" in result["data"]["message"]

    @pytest.mark.asyncio
    async def test_analyze_error(self):
        agent = MagicMock()
        agent.analyze = AsyncMock(side_effect=RuntimeError("boom"))
        h = _handle(agent=agent)
        with pytest.importorskip("unittest.mock").patch(
            "vibe_trading.tools.market_data_tools.get_current_price",
            new=AsyncMock(return_value={"price": 1.0}),
        ):
            result = await h._execute_agent()
        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestSend:
    @pytest.mark.asyncio
    async def test_send_result(self):
        ch = MessageChannel(enable_dedup=False)
        h = _handle(channel=ch)
        await h.send_result({"status": "ok"})
        assert h.messages_sent == 1
        got = await ch.get(timeout=1.0)
        assert got is not None
        assert got.sender == "analyst_1"

    @pytest.mark.asyncio
    async def test_send_error(self):
        ch = MessageChannel(enable_dedup=False)
        h = _handle(channel=ch)
        await h.send_error("something broke")
        got = await ch.get(timeout=1.0)
        assert got is not None
        assert got.message_type.value == "error"

    @pytest.mark.asyncio
    async def test_send_message(self):
        from vibe_trading.agents.messaging import MessageType
        ch = MessageChannel(enable_dedup=False)
        h = _handle(channel=ch)
        await h.send_message(MessageType.INFO, {"data": 1})
        got = await ch.get(timeout=1.0)
        assert got is not None


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        h = _handle(agent=object())  # 無 initialize → 跳過初始化

        async def _run():
            await asyncio_sleep(3600)

        h._run = _run
        await h.start()
        assert h.running is True
        await h.stop()
        assert h.running is False

    @pytest.mark.asyncio
    async def test_start_initialize_agent(self):
        agent = MagicMock()
        agent.initialize = AsyncMock()
        h = _handle(agent=agent)

        async def _run():
            await asyncio_sleep(3600)

        h._run = _run
        await h.start()
        agent.initialize.assert_called_once()
        assert h._initialized is True
        await h.stop()

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        h = _handle()
        await h.stop()  # 不 raise


def asyncio_sleep(sec):
    import asyncio
    return asyncio.sleep(sec)
