"""Tests for BinanceKlineWS + agent_factory helpers (Wave D — coverage)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.agents.agent_factory import (
    StreamPrinter,
    create_analysis_prompt,
    format_market_data_for_agent,
)
from vibe_trading.data_sources.kline.binance_ws import BinanceKlineWS


class TestBinanceKlineWS:
    def test_init(self):
        ws = BinanceKlineWS(max_buffer_size=10)
        assert ws._available is False
        assert ws._running is False

    @pytest.mark.asyncio
    async def test_subscribe(self):
        ws = BinanceKlineWS()
        ws._ws = MagicMock()
        ws._ws.send = AsyncMock()
        await ws._subscribe("BTCUSDT", "30m")
        ws._ws.send.assert_called_once()
        payload = ws._ws.send.call_args[0][0]
        assert "btcusdt@kline_30m" in payload

    @pytest.mark.asyncio
    async def test_subscribe_no_ws(self):
        ws = BinanceKlineWS()
        await ws._subscribe("BTCUSDT", "30m")  # 不 raise

    def test_is_available(self):
        ws = BinanceKlineWS()
        assert ws.is_available is False
        ws._available = True
        assert ws.is_available is True

    @pytest.mark.asyncio
    async def test_close(self):
        ws = BinanceKlineWS()
        ws._running = True
        ws._ws = MagicMock()
        ws._ws.close = AsyncMock()
        await ws.close()
        assert ws._running is False


class TestStreamPrinter:
    def test_on_event_message(self):
        sp = StreamPrinter("tech")
        event = MagicMock()
        event.type = "message"
        event.message = MagicMock()
        event.message.content = [MagicMock(text="分析內容")]
        sp.on_event(event)  # 不 raise

    def test_on_event_unknown(self):
        sp = StreamPrinter("tech")
        sp.on_event(MagicMock(type="unknown"))  # 不 raise


class TestFormatMarketData:
    def test_error(self):
        assert "Error" in format_market_data_for_agent({"error": "down"})

    def test_full_data(self):
        data = {
            "symbol": "BTCUSDT", "interval": "30m",
            "latest": {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            "indicators": {"rsi": 55.5, "macd": 0.01, "bollinger_upper": 2.0,
                           "bollinger_lower": 0.5},
        }
        text = format_market_data_for_agent(data)
        assert "BTCUSDT" in text
        assert "RSI: 55.50" in text

    def test_minimal_data(self):
        text = format_market_data_for_agent({"symbol": "BTCUSDT"})
        assert "BTCUSDT" in text


class TestCreateAnalysisPrompt:
    def test_prompt_basic(self):
        prompt = create_analysis_prompt("BTCUSDT", {"symbol": "BTCUSDT"})
        assert "BTCUSDT" in prompt
        assert "recommendation" in prompt

    def test_prompt_with_context(self):
        prompt = create_analysis_prompt("BTCUSDT", {}, additional_context="宏觀轉好")
        assert "宏觀轉好" in prompt
