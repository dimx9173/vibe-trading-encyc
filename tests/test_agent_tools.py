"""Tests for agent_tools execute functions (Wave D — coverage 85% plan).

每個 execute_* 是薄包裝 — mock 底層 tools 函式, 驗證 AgentToolResult 包裝.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.agents import agent_tools


def _params(cls, **kwargs):
    return cls(**kwargs)


class TestExecuteDataTools:
    @pytest.mark.asyncio
    async def test_execute_get_current_price(self):
        with patch.object(agent_tools.market_data_tools, "get_current_price",
                          new=AsyncMock(return_value={"price": 50000.0})):
            result = await agent_tools.execute_get_current_price(
                "x", _params(agent_tools.GetCurrentPriceParams, symbol="BTCUSDT"))
        assert result.content[0].text == "当前价格: 50000.0"

    @pytest.mark.asyncio
    async def test_execute_get_24hr_ticker(self):
        with patch.object(agent_tools.market_data_tools, "get_24hr_ticker",
                          new=AsyncMock(return_value={"price_change_percent": 1.5, "volume": 100})):
            result = await agent_tools.execute_get_24hr_ticker(
                "x", _params(agent_tools.Get24hrTickerParams, symbol="BTCUSDT"))
        assert "1.5%" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_funding_rate(self):
        with patch.object(agent_tools.market_data_tools, "get_funding_rate",
                          new=AsyncMock(return_value={"funding_rate": 0.0001, "mark_price": 50000})):
            result = await agent_tools.execute_get_funding_rate(
                "x", _params(agent_tools.GetFundingRateParams, symbol="BTCUSDT"))
        assert "资金费率: 0.0001" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_long_short_ratio(self):
        with patch.object(agent_tools.fundamental_tools, "get_long_short_ratio",
                          new=AsyncMock(return_value={"long_short_ratio": 1.5})):
            result = await agent_tools.execute_get_long_short_ratio(
                "x", _params(agent_tools.GetLongShortRatioParams, symbol="BTCUSDT"))
        assert "1.5" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_open_interest(self):
        with patch.object(agent_tools.market_data_tools, "get_open_interest",
                          new=AsyncMock(return_value={"open_interest": 12345})):
            result = await agent_tools.execute_get_open_interest(
                "x", _params(agent_tools.GetOpenInterestParams, symbol="BTCUSDT"))
        assert "12345" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_fear_and_greed(self):
        with patch.object(agent_tools.sentiment_tools, "get_fear_and_greed_index",
                          new=AsyncMock(return_value={"value": 55, "value_classification": "Neutral"})):
            result = await agent_tools.execute_get_fear_and_greed(
                "x", _params(agent_tools.GetFearAndGreedParams))
        assert "55" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_news_sentiment(self):
        with patch.object(agent_tools.sentiment_tools, "get_news_sentiment",
                          new=AsyncMock(return_value={"news": [{"title": "BTC 看漲"}]})):
            result = await agent_tools.execute_get_news_sentiment(
                "x", _params(agent_tools.GetNewsSentimentParams, symbol="BTCUSDT"))
        assert "BTC 看漲" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_order_book(self):
        with patch.object(agent_tools.market_data_tools, "get_order_book",
                          new=AsyncMock(return_value={"bids": [[50000, 1]], "asks": []})):
            result = await agent_tools.execute_get_order_book(
                "x", _params(agent_tools.GetOrderBookParams, symbol="BTCUSDT"))
        assert result.content[0].text  # 非空

    @pytest.mark.asyncio
    async def test_execute_get_social_sentiment(self):
        with patch.object(agent_tools.sentiment_tools, "get_social_sentiment",
                          new=AsyncMock(return_value={"sentiment_score": 0.7, "mentions": {"total": 100}})):
            result = await agent_tools.execute_get_social_sentiment(
                "x", _params(agent_tools.GetSocialSentimentParams, symbol="BTCUSDT"))
        assert "0.7" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_taker_buy_sell_ratio(self):
        with patch.object(agent_tools.fundamental_tools, "get_taker_buy_sell_ratio",
                          new=AsyncMock(return_value={"buy_ratio": 1.2, "sell_ratio": 0.8})):
            result = await agent_tools.execute_get_taker_buy_sell_ratio(
                "x", _params(agent_tools.GetTakerBuySellRatioParams, symbol="BTCUSDT"))
        assert "1.2" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_top_trader_ratio(self):
        with patch.object(agent_tools.fundamental_tools, "get_top_trader_long_short_ratio",
                          new=AsyncMock(return_value={"long_short_ratio": 0.8})):
            result = await agent_tools.execute_get_top_trader_long_short_ratio(
                "x", _params(agent_tools.GetTopTraderLongShortRatioParams, symbol="BTCUSDT"))
        assert "0.8" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_liquidation_orders(self):
        with patch.object(agent_tools.fundamental_tools, "get_liquidation_orders",
                          new=AsyncMock(return_value={"count": 3})):
            result = await agent_tools.execute_get_liquidation_orders(
                "x", _params(agent_tools.GetLiquidationOrdersParams, symbol="BTCUSDT"))
        assert result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_trending_symbols(self):
        with patch.object(agent_tools.sentiment_tools, "get_trending_symbols",
                          new=AsyncMock(return_value={"symbols": ["BTCUSDT"]})):
            result = await agent_tools.execute_get_trending_symbols(
                "x", _params(agent_tools.GetTrendingSymbolsParams))
        assert result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_comprehensive_sentiment(self):
        with patch.object(agent_tools.sentiment_tools, "get_comprehensive_sentiment",
                          new=AsyncMock(return_value={"overall_score": 40, "signal": "Buy"})):
            result = await agent_tools.execute_get_comprehensive_sentiment(
                "x", _params(agent_tools.GetComprehensiveSentimentParams, symbol="BTCUSDT"))
        assert "40" in result.content[0].text


class TestExecuteTechnicalTools:
    @pytest.mark.asyncio
    async def test_execute_get_technical_indicators(self):
        with patch.object(agent_tools.technical_tools, "get_technical_indicators",
                          new=AsyncMock(return_value={"indicators": {"rsi": 50}})):
            result = await agent_tools.execute_get_technical_indicators(
                "x", _params(agent_tools.GetTechnicalIndicatorsParams, symbol="BTCUSDT"))
        assert result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_analyze_trend(self):
        with patch.object(agent_tools.technical_tools, "analyze_trend",
                          new=AsyncMock(return_value={"analysis": {"trend": "up"}})):
            result = await agent_tools.execute_analyze_trend(
                "x", _params(agent_tools.AnalyzeTrendParams, symbol="BTCUSDT"))
        assert result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_get_comprehensive_technical(self):
        with patch.object(agent_tools.technical_tools, "get_comprehensive_technical_analysis",
                          new=AsyncMock(return_value={"summary": "bullish"})):
            result = await agent_tools.execute_get_comprehensive_technical_analysis(
                "x", _params(agent_tools.GetComprehensiveTechnicalAnalysisParams, symbol="BTCUSDT"))
        assert result.content[0].text


class TestToolRegistry:
    def test_get_all_tools(self):
        tools = agent_tools.get_all_tools()
        names = [t.name for t in tools]
        assert "get_current_price" in names
        assert "get_funding_rate" in names
        assert "analyze_trend" in names
        assert "detect_candlestick_patterns" in names

    def test_pytool_parameters_schema(self):
        tools = agent_tools.get_all_tools()
        t = next(x for x in tools if x.name == "get_current_price")
        assert "symbol" in t.parameters["properties"]

    @pytest.mark.asyncio
    async def test_pytool_execute_dict_params(self):
        tool = next(x for x in agent_tools.get_all_tools() if x.name == "get_current_price")
        with patch.object(agent_tools.market_data_tools, "get_current_price",
                          new=AsyncMock(return_value={"price": 100.0})):
            result = await tool.execute("id", {"symbol": "BTCUSDT"})
        assert "100.0" in result.content[0].text


class TestToolFactories:
    def test_get_execution_tools(self):
        tools = agent_tools.get_execution_tools(MagicMock())
        assert len(tools) == 1
        assert tools[0].name == "submit_trade_order"

    def test_get_technical_tools(self):
        tools = agent_tools.get_technical_tools(MagicMock())
        assert len(tools) == 1
        assert tools[0].name == "compose_factor"

    def test_get_tools_for_agent(self):
        tools = agent_tools.get_tools_for_agent("fundamental_analyst")
        assert isinstance(tools, list)
        names = [t.name for t in tools]
        assert "get_funding_rate" in names

    def test_get_tools_for_unknown_agent(self):
        tools = agent_tools.get_tools_for_agent("mystery_role")
        assert isinstance(tools, list)


class TestTechnicalAnalystTools:
    def test_get_tools_for_technical(self):
        tools = agent_tools.get_tools_for_agent("technical_analyst")
        names = [t.name for t in tools]
        assert "get_technical_indicators" in names
        assert "get_current_price" in names
