"""Tests for sentiment/fundamental tools via httpx MockTransport (Wave C).

策略: httpx.MockTransport 攔截 API 回應 — 不發真實請求;
sentiment 需 cryptocmp_api_key → mock settings.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from vibe_trading.tools import fundamental_tools, sentiment_tools


_ORIG_ASYNC_CLIENT = httpx.AsyncClient  # patch 前保存原始類別 (避免 side_effect 遞迴)


def _transport(handler):
    """建立 httpx MockTransport (async handler)."""
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _reset_news_cache():
    """每個測試前重置 module cache + 恢復原始工具函式.

    test_agent_backtest.py 的 install_replay_tool_isolation 會永久替換
    fundamental/sentiment tools (無 uninstall) — reload 恢復原始 body,
    確保 coverage 追蹤到真實實作.
    """
    import importlib

    from vibe_trading.tools import fundamental_tools as _ft
    from vibe_trading.tools import sentiment_tools as _st

    importlib.reload(_ft)
    importlib.reload(_st)
    _st._news_cache = {"data": None, "timestamp": 0, "ttl": 300}
    yield
    _st._news_cache = {"data": None, "timestamp": 0, "ttl": 300}


class TestFundingRates:
    @pytest.mark.asyncio
    async def test_single_symbol(self):
        async def handler(request):
            return httpx.Response(200, json={
                "symbol": "BTCUSDT", "lastFundingRate": "0.0001", "markPrice": "50000",
            })

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_funding_rates("BTCUSDT")
        assert result["symbol"] == "BTCUSDT"
        assert result["funding_rate"] == 0.0001

    @pytest.mark.asyncio
    async def test_list_all(self):
        async def handler(request):
            return httpx.Response(200, json=[
                {"symbol": "BTCUSDT", "lastFundingRate": "0.0001", "markPrice": "50000"},
                {"symbol": "ETHUSDT", "lastFundingRate": "0.0002", "markPrice": "3000"},
            ])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_funding_rates()
        assert isinstance(result, list) and len(result) == 2
        assert result[1]["funding_rate"] == 0.0002

    @pytest.mark.asyncio
    async def test_error_returns_dict(self):
        async def handler(request):
            raise httpx.ConnectError("network down")

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_funding_rates("BTCUSDT")
        assert "error" in result


class TestLongShortRatio:
    @pytest.mark.asyncio
    async def test_parses_latest(self):
        async def handler(request):
            return httpx.Response(200, json=[
                {"longShortRatio": "1.5", "longAccount": "0.6",
                 "shortAccount": "0.4", "timestamp": 123},
                {"longShortRatio": "2.0", "longAccount": "0.67",
                 "shortAccount": "0.33", "timestamp": 456},
            ])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_long_short_ratio("BTCUSDT")
        assert result["long_short_ratio"] == 2.0  # 取最新
        assert result["timestamp"] == 456

    @pytest.mark.asyncio
    async def test_empty_returns_error(self):
        async def handler(request):
            return httpx.Response(200, json=[])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_long_short_ratio("BTCUSDT")
        assert result == {"error": "No data available"}


class TestTakerBuySell:
    @pytest.mark.asyncio
    async def test_parses(self):
        async def handler(request):
            return httpx.Response(200, json=[
                {"buySellRatio": "1.2", "buyVol": "100", "sellVol": "80", "timestamp": 1},
            ])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_taker_buy_sell_ratio("BTCUSDT")
        assert result["buy_sell_ratio"] == 1.2
        assert result["buy_volume"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_returns_error(self):
        async def handler(request):
            return httpx.Response(200, json=[])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_taker_buy_sell_ratio("BTCUSDT")
        assert result == {"error": "No data available"}


class TestOpenInterest:
    @pytest.mark.asyncio
    async def test_parses(self):
        async def handler(request):
            return httpx.Response(200, json=[
                {"sumOpenInterest": "50000", "sumOpenInterestValue": "2.5e9", "timestamp": 1},
            ])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_open_interest("BTCUSDT")
        assert result["open_interest"] == 50000.0

    @pytest.mark.asyncio
    async def test_empty_returns_error(self):
        async def handler(request):
            return httpx.Response(200, json=[])

        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await fundamental_tools.get_open_interest("BTCUSDT")
        assert result == {"error": "No data available"}


class TestSentimentTools:
    @pytest.mark.asyncio
    async def test_news_no_api_key(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = ""
        with patch("vibe_trading.config.settings.get_settings", return_value=settings):
            result = await sentiment_tools.get_news_sentiment("BTCUSDT")
        assert result["error"] == "CRYPTOCOMPARE_API_KEY not configured"

    @pytest.mark.asyncio
    async def test_news_with_data(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"

        async def handler(request):
            return httpx.Response(200, json={"Data": [
                {"title": "Bitcoin surges to new high", "body": "BTC rally continues",
                 "source": "coindesk", "url": "u1", "published_on": 123, "categories": ["BTC"]},
            ]})

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_news_sentiment("BTCUSDT", limit=5)
        assert result["available"] is True
        assert result["overall_sentiment"] == "positive"  # "surge"/"rally" 正面詞
        assert result["news_count"] == 1

    @pytest.mark.asyncio
    async def test_news_empty_data(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"

        async def handler(request):
            return httpx.Response(200, json={"Data": []})

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_news_sentiment("BTCUSDT")
        assert result["available"] is False  # Data 空 → API error 分支

    @pytest.mark.asyncio
    async def test_news_cache_used(self):
        """module cache 命中時不發請求."""
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"
        sentiment_tools._news_cache = {
            "data": {"Data": [{"title": "cached title", "body": "cached body",
                               "source": "s", "url": "u", "published_on": 1,
                               "categories": []}]},
            "timestamp": __import__("time").time(),
            "ttl": 300,
        }
        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient") as mock_client:
            result = await sentiment_tools.get_news_sentiment("BTCUSDT", limit=5)
            # AsyncClient() 構造會呼叫, 但 cache 命中時 .get() 不該被呼叫
            mock_client.return_value.get.assert_not_called()
        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_news_bad_status(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"

        async def handler(request):
            return httpx.Response(200, json={"Data": None})

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_news_sentiment("BTCUSDT")
        assert result["available"] is False

    @pytest.mark.asyncio
    async def test_news_symbol_mapping(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"

        async def handler(request):
            # ETHUSDT → "ETH" 出現在 keywords
            return httpx.Response(200, json={"Data": [
                {"title": "Ethereum upgrade launch", "body": "ETH grows",
                 "source": "s", "url": "u", "published_on": 1, "categories": []},
            ]})

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_news_sentiment("ETHUSDT", limit=5)
        assert result["available"] is True
        assert result["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_news_exception(self):
        settings = MagicMock()
        settings.cryptocmp_api_key = "testkey"

        async def handler(request):
            raise httpx.ConnectError("down")

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_news_sentiment("BTCUSDT")
        assert result["available"] is False


class TestFearGreed:
    @pytest.mark.asyncio
    async def test_fear_greed_classification(self):
        async def handler(request):
            return httpx.Response(200, json={"data": [
                {"value": "15", "value_classification": "Extreme Fear",
                 "timestamp": "123"},
            ]})

        with patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_fear_and_greed_index()
        assert result["value"] == 15
        assert result["sentiment"] == "extreme_fear"

    @pytest.mark.asyncio
    async def test_fear_greed_greed(self):
        async def handler(request):
            return httpx.Response(200, json={"data": [
                {"value": "70", "value_classification": "Greed",
                 "timestamp": "123"},
            ]})

        with patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_fear_and_greed_index()
        assert result["sentiment"] == "greed"

    @pytest.mark.asyncio
    async def test_fear_greed_extreme_greed(self):
        async def handler(request):
            return httpx.Response(200, json={"data": [
                {"value": "90", "value_classification": "Extreme Greed",
                 "timestamp": "123"},
            ]})

        with patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_fear_and_greed_index()
        assert result["sentiment"] == "extreme_greed"

    @pytest.mark.asyncio
    async def test_fear_greed_error(self):
        async def handler(request):
            raise httpx.ConnectError("down")

        with patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_fear_and_greed_index()
        assert "error" in result


class TestSocialSentiment:
    @pytest.mark.asyncio
    async def test_no_keys_unavailable(self):
        settings = MagicMock()
        settings.lunarcrush_api_key = ""
        settings.cryptocmp_api_key = ""
        with patch("vibe_trading.config.settings.get_settings", return_value=settings):
            result = await sentiment_tools.get_social_sentiment("BTCUSDT")
        assert result["available"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_lunarcrush_success(self):
        settings = MagicMock()
        settings.lunarcrush_api_key = "lc_key"
        settings.cryptocmp_api_key = ""

        async def handler(request):
            return httpx.Response(200, json={"data": [
                {"sentiment": 8, "social_score": 100, "galaxy_score": 50,
                 "close": 50000, "social_volume": 1000, "social_volume_24h_change": 10,
                 "social_contributors": 500, "social_score_global_ranking": 3},
            ]})

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient",
                          return_value=httpx.AsyncClient(transport=_transport(handler))):
            result = await sentiment_tools.get_social_sentiment("BTCUSDT")
        assert result["available"] is True
        assert result["source"] == "LunarCrush"
        assert result["sentiment"] == "very_bullish"
        assert result["sentiment_score"] == 8

    @pytest.mark.asyncio
    async def test_lunarcrush_fallback_cryptocompare(self):
        settings = MagicMock()
        settings.lunarcrush_api_key = "lc_key"
        settings.cryptocmp_api_key = "cc_key"

        async def handler(request):
            url = str(request.url)
            if "lunarcrush" in url:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"Data": [
                {"twitter_followers": 1000, "reddit_users": 200, "change": 8,
                 "code_repo_mentions": 5, "followers": 1200},
            ]})

        def _new_client():
            return _ORIG_ASYNC_CLIENT(transport=_transport(handler))

        with patch("vibe_trading.config.settings.get_settings", return_value=settings), \
             patch.object(sentiment_tools.httpx, "AsyncClient", side_effect=_new_client):
            result = await sentiment_tools.get_social_sentiment("BTCUSDT")
        assert result["available"] is True
        assert result["source"] == "CryptoCompare"
        assert result["sentiment"] == "very_bullish"  # change 8 > 5


class TestComprehensive:
    @pytest.mark.asyncio
    async def test_all_available(self):
        """三源齊備 → 加權分數 + bullish 分級."""
        with patch.object(sentiment_tools, "get_fear_and_greed_index",
                          new=AsyncMock(return_value={"value": 80})), \
             patch.object(sentiment_tools, "get_social_sentiment",
                          new=AsyncMock(return_value={"available": True, "sentiment_score": 40})), \
             patch.object(sentiment_tools, "get_news_sentiment",
                          new=AsyncMock(return_value={"available": True, "overall_sentiment": "positive"})):
            result = await sentiment_tools.get_comprehensive_sentiment("BTCUSDT")
        assert result["available_sources"] == ["fear_greed", "social", "news"]
        assert result["sentiment_score"] == pytest.approx(40.0)  # (30*.3+40*.4+50*.3)/1.0
        assert result["overall_sentiment"] == "very_bullish"  # 40 > 30

    @pytest.mark.asyncio
    async def test_only_fng(self):
        with patch.object(sentiment_tools, "get_fear_and_greed_index",
                          new=AsyncMock(return_value={"value": 10})), \
             patch.object(sentiment_tools, "get_social_sentiment",
                          new=AsyncMock(return_value={"available": False})), \
             patch.object(sentiment_tools, "get_news_sentiment",
                          new=AsyncMock(return_value={"available": False})):
            result = await sentiment_tools.get_comprehensive_sentiment("BTCUSDT")
        assert result["available_sources"] == ["fear_greed"]
        assert result["overall_sentiment"] == "very_bearish"  # (10-50) = -40 → ≤ -30

    @pytest.mark.asyncio
    async def test_no_sources(self):
        with patch.object(sentiment_tools, "get_fear_and_greed_index",
                          new=AsyncMock(return_value={})), \
             patch.object(sentiment_tools, "get_social_sentiment",
                          new=AsyncMock(return_value={"available": False})), \
             patch.object(sentiment_tools, "get_news_sentiment",
                          new=AsyncMock(return_value={"available": False})):
            result = await sentiment_tools.get_comprehensive_sentiment("BTCUSDT")
        assert result["available_sources"] == []
        assert result["sentiment_score"] == 0
        assert result["overall_sentiment"] == "neutral"


class TestTrending:
    @pytest.mark.asyncio
    async def test_trending_unavailable(self):
        result = await sentiment_tools.get_trending_symbols()
        assert result["available"] is False
        assert "error" in result
