"""Tests for PrimeAgent pure logic (Wave D — coverage 85% plan).

PrimeAgent 構造需 LLM config + pi_agent_core — 用 __new__ 跳過 __init__,
手動注入 config, 測試監控/價格/格式等純邏輯方法.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.prime.models import PrimeAgentConfig, PrimeConfig
from vibe_trading.prime.prime_agent import PrimeAgent, PrimeAgentStatus


def _agent(price: float | None = None) -> PrimeAgent:
    a = PrimeAgent.__new__(PrimeAgent)
    a.config = PrimeAgentConfig()
    a.prime_config = PrimeConfig(symbol="BTCUSDT")
    a.status = PrimeAgentStatus.INITIALIZING
    a.stats = {"messages_processed": 0, "decisions_made": 0,
               "emergency_decisions": 0, "constraint_violations": 0, "start_time": None}
    a.decision_history = []
    a.emergency_agents = {}
    a._monitoring_running = False
    a._monitoring_paused = False
    a._last_price = None
    a._last_price_time = None
    a._last_logged_position = None
    if price is not None:
        a._last_price = price
        a._last_price_time = datetime.now()
    return a


class TestGetCurrentPrice:
    @pytest.mark.asyncio
    async def test_returns_price_from_dict(self):
        a = _agent()
        with patch("vibe_trading.tools.market_data_tools.get_current_price",
                   new=AsyncMock(return_value={"price": 50000.0})):
            price = await a._get_current_price()
        assert price == 50000.0

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        a = _agent()
        with patch("vibe_trading.tools.market_data_tools.get_current_price",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            assert await a._get_current_price() is None


class TestPriceMovement:
    @pytest.mark.asyncio
    async def test_first_price_initializes(self):
        a = _agent()
        await a._check_price_movement(50000.0)
        assert a._last_price == 50000.0
        assert a.stats["emergency_decisions"] == 0

    @pytest.mark.asyncio
    async def test_crash_triggers_emergency(self):
        a = _agent(price=50000.0)
        # 暴跌 > crash_threshold (預設 -0.05)
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as mock_crash:
            await a._check_price_movement(46000.0)
        mock_crash.assert_called_once()

    @pytest.mark.asyncio
    async def test_spike_triggers(self):
        a = _agent(price=50000.0)
        with patch.object(a, "_handle_price_spike", new=AsyncMock()) as mock_spike:
            await a._check_price_movement(55000.0)  # +10% > pump_threshold
        mock_spike.assert_called_once()

    @pytest.mark.asyncio
    async def test_normal_movement_no_action(self):
        a = _agent(price=50000.0)
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as c, \
             patch.object(a, "_handle_price_spike", new=AsyncMock()) as s:
            await a._check_price_movement(50100.0)  # +0.2%
        c.assert_not_called()
        s.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_type_ignored(self):
        a = _agent()
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as c:
            await a._check_price_movement("not-a-number")
        c.assert_not_called()


class TestPriceHandlers:
    @pytest.mark.asyncio
    async def test_crash_creates_close_all(self):
        a = _agent()
        with patch.object(a, "_execute_emergency_decision", new=AsyncMock()) as ex:
            await a._handle_price_crash(46000.0, -0.08)
        ex.assert_called_once()
        decision = ex.call_args[0][0]
        assert decision.action.value == "close_all"

    @pytest.mark.asyncio
    async def test_spike_recommends_hold(self):
        a = _agent()
        await a._handle_price_spike(55000.0, 0.10)
        assert a.decision_history == []  # spike 不自動執行


class TestFormatAndSummary:
    def test_format_message_as_prompt(self):
        a = _agent()
        msg = MagicMock()
        msg.sender = "analyst"
        msg.message_type.value = "report"
        msg.content = {"text": "BTC 看漲"}
        msg.metadata = {}
        result = a._format_message_as_prompt(msg)
        assert "analyst" in result
        assert "BTC" in result

    def test_summarize_content_dict(self):
        a = _agent()
        result = a._summarize_content({"action": "BUY", "price": 50000})
        assert "BUY" in result

    def test_summarize_content_mixed_types(self):
        a = _agent()
        result = a._summarize_content({"n": 1, "d": {"x": 1}, "l": [1, 2]})
        assert "n: 1" in result
        assert "复杂数据" in result
        assert "长度2" in result

    def test_summarize_content_empty(self):
        a = _agent()
        assert a._summarize_content({}) == ""


class TestMessageStats:
    def test_record_message(self):
        from vibe_trading.prime.models import MessageStats
        stats = MessageStats()
        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.metadata = {"priority": "normal"}
        stats.record_message(msg, 0.5)
        stats.record_message(msg, 1.5)
        assert stats.total_messages == 2
        assert stats.messages_by_type["report"] == 2
        assert stats.messages_by_agent["analyst"] == 2
        assert 0.1 <= stats.average_processing_time <= 1.5
        assert stats.last_message_time is not None
