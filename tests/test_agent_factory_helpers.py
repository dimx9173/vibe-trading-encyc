"""Tests for agent_factory — Wave D119."""
from unittest.mock import MagicMock, patch

import pytest

from vibe_trading.agents.agent_factory import (
    ToolContext,
    create_analysis_prompt,
    create_trading_agent,
    format_market_data_for_agent,
    setup_streaming,
    StreamPrinter,
)


class TestToolContext:
    def test_defaults(self):
        ctx = ToolContext(symbol="BTCUSDT", interval="30m")
        assert ctx.symbol == "BTCUSDT"
        assert ctx.interval == "30m"
        assert ctx.storage is None
        assert ctx.executor is None
        assert ctx.risk_gate is None
        assert ctx.current_bar_open_time_ms is None

    def test_custom(self):
        storage = MagicMock()
        ctx = ToolContext("BTCUSDT", "30m", storage=storage)
        assert ctx.storage is storage


class TestFormatMarketData:
    def test_error(self):
        assert "Error:" in format_market_data_for_agent({"error": "boom"})

    def test_full(self):
        data = {
            "symbol": "BTCUSDT", "interval": "30m",
            "latest": {"open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
            "indicators": {"rsi": 50.0, "macd": 0.5,
                           "bollinger_upper": 2.0, "bollinger_lower": 1.0},
        }
        out = format_market_data_for_agent(data)
        assert "BTCUSDT" in out
        assert "RSI: 50.00" in out
        assert "Bollinger" in out

    def test_minimal(self):
        out = format_market_data_for_agent({"symbol": "X"})
        assert out == "Symbol: X\nInterval: N/A"


class TestAnalysisPrompt:
    def test_builds(self):
        prompt = create_analysis_prompt("BTCUSDT", {"symbol": "BTCUSDT"})
        assert "BTCUSDT" in prompt

    def test_with_context(self):
        prompt = create_analysis_prompt("BTCUSDT", {"symbol": "BTCUSDT"},
                                        additional_context="extra ctx")
        assert "extra ctx" in prompt


class TestStreamPrinter:
    def _evt(self, etype, message=None):
        evt = MagicMock()
        evt.type = etype
        evt.message = message
        return evt

    def _msg(self, blocks):
        msg = MagicMock()
        msg.content = blocks
        return msg

    def test_disabled(self):
        StreamPrinter.enabled = False
        try:
            p = StreamPrinter("a")
            p.on_event(self._evt("message_start"))
            p.on_event(self._evt("message_update",
                                  self._msg([MagicMock(text="hello")])))
        finally:
            StreamPrinter.enabled = True
        assert p._started is False

    def test_message_start(self):
        p = StreamPrinter("a")
        p.on_event(self._evt("message_start"))
        assert p._started is True

    def test_update_before_start_ignored(self):
        p = StreamPrinter("a")
        p.on_event(self._evt("message_update",
                             self._msg([MagicMock(text="x")])))
        assert p._line_buffer == ""

    def test_update_text_stream(self):
        from pi_agent_core.types import TextContent
        p = StreamPrinter("a")
        p.on_event(self._evt("message_start"))
        block = TextContent(type="text", text="hello\nworld")
        p.on_event(self._evt("message_update", self._msg([block])))
        assert p._buffer == "hello\nworld"
        assert p._last_printed_len == len("hello\nworld")

    def test_update_thinking(self):
        from pi_ai import ThinkingContent
        p = StreamPrinter("a")
        p.on_event(self._evt("message_start"))
        block = ThinkingContent(type="thinking", thinking="deep thoughts")
        p.on_event(self._evt("message_update", self._msg([block])))
        assert p._buffer == ""

    def test_message_end_flushes(self):
        from pi_agent_core.types import TextContent
        p = StreamPrinter("a")
        p.on_event(self._evt("message_start"))
        block = TextContent(type="text", text="done")
        p.on_event(self._evt("message_update", self._msg([block])))
        p.on_event(self._evt("message_end"))
        assert p._started is False

    def test_setup_streaming_subscribes(self):
        agent = MagicMock()
        setup_streaming(agent, "Trader")
        agent.subscribe.assert_called_once()


class TestCreateTradingAgent:
    @pytest.mark.asyncio
    async def test_create(self):
        from vibe_trading.config.agent_config import AgentConfig
        cfg = AgentConfig(name="Trader", role="trader", temperature=0.3)
        ctx = ToolContext("BTCUSDT", "30m")
        agent = MagicMock()
        with patch("vibe_trading.agents.agent_factory.get_settings",
                   return_value=MagicMock(llm_config_name="default")), \
             patch("vibe_trading.agents.agent_factory.get_model_from_config",
                   return_value="model-x"), \
             patch("vibe_trading.agents.agent_factory.make_get_api_key",
                   return_value=lambda: "key"), \
             patch("vibe_trading.agents.agent_factory.get_agent_prompt",
                   return_value="prompt"), \
             patch("vibe_trading.agents.agent_tools.get_tools_for_agent",
                   return_value=[]), \
             patch("vibe_trading.agents.agent_factory.Agent",
                   return_value=agent):
            created = await create_trading_agent(cfg, ctx)
        assert created is agent

    @pytest.mark.asyncio
    async def test_create_with_additional_tools_and_streaming(self):
        from vibe_trading.config.agent_config import AgentConfig
        cfg = AgentConfig(name="Trader", role="trader", temperature=0.3)
        ctx = ToolContext("BTCUSDT", "30m")
        agent = MagicMock()
        extra = MagicMock()
        with patch("vibe_trading.agents.agent_factory.get_settings",
                   return_value=MagicMock(llm_config_name="default")), \
             patch("vibe_trading.agents.agent_factory.get_model_from_config",
                   return_value="model-x"), \
             patch("vibe_trading.agents.agent_factory.make_get_api_key",
                   return_value=lambda: "key"), \
             patch("vibe_trading.agents.agent_factory.get_agent_prompt",
                   return_value="prompt"), \
             patch("vibe_trading.agents.agent_tools.get_tools_for_agent",
                   side_effect=RuntimeError("no tools")), \
             patch("vibe_trading.agents.agent_factory.Agent",
                   return_value=agent), \
             patch("vibe_trading.agents.agent_factory.setup_streaming",
                   new=MagicMock()):
            created = await create_trading_agent(
                cfg, ctx, additional_tools=[extra],
                enable_streaming=True, agent_name="Trader")
        assert created is agent
