"""Tests for tools layers (Wave C — coverage 85% plan).

策略: technical/market_data tools 用 mock storage 覆蓋計算路徑;
BinanceClient 依賴用 mock REST 覆蓋解析路徑 (不發真實請求).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.data_sources.base import Kline
from vibe_trading.tools import (
    market_data_tools,
    technical_tools,
)


def _klines(n: int = 60, base: float = 100.0, step: float = 1.0) -> list[Kline]:
    return [
        Kline(
            symbol="BTCUSDT", interval="30m",
            open_time=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(hour=i % 24),
            open=base + step * i * 0.99, high=base + step * i * 1.01,
            low=base + step * i * 0.98, close=base + step * i,
            volume=100.0,
            close_time=int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
        )
        for i in range(n)
    ]


def _mock_storage(klines=None):
    s = MagicMock()
    s.query_klines = AsyncMock(return_value=klines or _klines())
    s.get_latest_kline = AsyncMock(return_value=(klines or _klines())[-1])
    return s


@pytest.fixture(autouse=True)
def _restore_tool_functions():
    """恢復被 install_replay_tool_isolation 替換的 technical/market_data 函式."""
    import importlib

    from vibe_trading.tools import market_data_tools as _mdt
    from vibe_trading.tools import technical_tools as _tt

    importlib.reload(_tt)
    importlib.reload(_mdt)
    yield


class TestTechnicalTools:
    async def test_no_storage_returns_error(self):
        result = await technical_tools.get_technical_indicators("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_insufficient_data(self):
        s = _mock_storage(_klines(10))
        result = await technical_tools.get_technical_indicators("BTCUSDT", storage=s)
        assert "error" in result

    async def test_full_indicators(self):
        s = _mock_storage()
        result = await technical_tools.get_technical_indicators("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"
        assert "rsi" in result["indicators"]
        assert "macd" in result["indicators"]
        assert "bollinger_upper" in result["indicators"]

    async def test_analyze_trend_no_storage(self):
        result = await technical_tools.analyze_trend("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_analyze_trend_full(self):
        s = _mock_storage()
        result = await technical_tools.analyze_trend("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"
        assert "price_change_pct" in result["analysis"]

    async def test_analyze_trend_insufficient(self):
        s = _mock_storage(_klines(10))
        result = await technical_tools.analyze_trend("BTCUSDT", storage=s)
        assert "error" in result

    async def test_detect_support_resistance_no_storage(self):
        result = await technical_tools.detect_support_resistance("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_detect_support_resistance_full(self):
        s = _mock_storage()
        result = await technical_tools.detect_support_resistance("BTCUSDT", storage=s)
        assert "support_levels" in result
        assert "resistance_levels" in result

    async def test_calculate_pivots(self):
        s = _mock_storage()
        result = await technical_tools.calculate_pivots("BTCUSDT", storage=s)
        assert "pivot" in result or "error" in result

    async def test_detect_candlestick_patterns_no_storage(self):
        result = await technical_tools.detect_candlestick_patterns("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_detect_candlestick_patterns_full(self):
        s = _mock_storage()
        result = await technical_tools.detect_candlestick_patterns("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"

    async def test_detect_divergence_no_storage(self):
        result = await technical_tools.detect_divergence("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_detect_divergence_full(self):
        s = _mock_storage()
        result = await technical_tools.detect_divergence("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"

    async def test_analyze_volume_patterns_no_storage(self):
        result = await technical_tools.analyze_volume_patterns("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_analyze_volume_patterns_full(self):
        s = _mock_storage()
        result = await technical_tools.analyze_volume_patterns("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"

    async def test_comprehensive_technical_no_storage(self):
        result = await technical_tools.get_comprehensive_technical_analysis("BTCUSDT")
        assert result == {"error": "Storage not configured"}

    async def test_comprehensive_technical_full(self):
        s = _mock_storage()
        result = await technical_tools.get_comprehensive_technical_analysis("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"


class TestMarketDataTools:
    async def test_get_current_price_from_storage(self):
        s = _mock_storage()
        result = await market_data_tools.get_current_price("BTCUSDT", storage=s)
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == pytest.approx(159.0)  # 最後一根 close

    async def test_get_current_price_provider_fallback(self):
        """storage 無資料 → provider 路徑 (mock)."""
        # 清除 cached decorator 污染的價格 cache (key: price:get_current_price:...)
        try:
            await market_data_tools._cache.invalidate_pattern("price:get_current_price")
        except Exception:
            pass
        s = MagicMock()
        s.get_latest_kline = AsyncMock(return_value=None)
        provider = MagicMock()
        provider.get_current_price = AsyncMock(return_value=50000.0)
        with patch.object(market_data_tools, "get_binance_provider", new=AsyncMock(return_value=provider)):
            # 用不同 symbol 規避 storage 測試的 cache 污染
            result = await market_data_tools.get_current_price("ETHUSDT", storage=s)
            assert result["price"] == 50000.0

    async def test_get_24hr_ticker_parses(self):
        fake_rest = MagicMock()
        fake_rest._request = AsyncMock(return_value={
            "symbol": "BTCUSDT", "priceChange": "-100.0", "priceChangePercent": "-0.5",
            "highPrice": "51000", "lowPrice": "49000", "volume": "1000",
            "quoteVolume": "5e7", "openPrice": "50000", "lastPrice": "49900",
        })
        with patch.object(market_data_tools, "BinanceClient") as mock_cls:
            mock_cls.return_value.rest = fake_rest
            mock_cls.return_value.close = AsyncMock()
            result = await market_data_tools.get_24hr_ticker("BTCUSDT")
        assert result["symbol"] == "BTCUSDT"
        assert result["price_change"] == -100.0
        assert result["high"] == 51000.0

    async def test_get_order_book_parses(self):
        fake_rest = MagicMock()
        fake_rest._request = AsyncMock(return_value={
            "bids": [["50000", "1.0"], ["49999", "2.0"]],
            "asks": [["50001", "1.5"]],
            "lastUpdateId": 123,
        })
        with patch.object(market_data_tools, "BinanceClient") as mock_cls:
            mock_cls.return_value.rest = fake_rest
            mock_cls.return_value.close = AsyncMock()
            result = await market_data_tools.get_order_book("BTCUSDT")
        assert result["bids"][0] == [50000.0, 1.0]
        assert result["timestamp"] == 123

    async def test_get_funding_rate_parses(self):
        fake_rest = MagicMock()
        fake_rest._request = AsyncMock(return_value={
            "symbol": "BTCUSDT", "lastFundingRate": "0.0001",
            "markPrice": "50000", "nextFundingTime": 123456789,
        })
        with patch.object(market_data_tools, "BinanceClient") as mock_cls:
            mock_cls.return_value.rest = fake_rest
            mock_cls.return_value.close = AsyncMock()
            result = await market_data_tools.get_funding_rate("BTCUSDT")
        assert result["symbol"] == "BTCUSDT"

    async def test_convert_standard_to_legacy(self):
        k = MagicMock()
        k.symbol = "BTCUSDT"
        k.interval = "30m"
        k.open_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        k.open = k.high = k.low = k.close = 100.0
        k.volume = 10.0
        k.close_time = k.open_time
        k.quote_volume = 1000.0
        k.trades = 5
        k.taker_buy_base = 6.0
        k.taker_buy_quote = 600.0
        k.is_final = True
        legacy = market_data_tools.convert_standard_to_legacy(k)
        assert legacy.symbol == "BTCUSDT"
        assert legacy.taker_buy_base == 6.0


class TestKlineDataTool:
    @pytest.mark.asyncio
    async def test_from_storage(self):
        s = MagicMock()
        k = MagicMock()
        k.open_time = 1000; k.open = 1; k.high = 2; k.low = 3
        k.close = 4; k.volume = 5
        s.query_klines = AsyncMock(return_value=[k])
        result = await market_data_tools.get_kline_data(
            "BTCUSDT", "30m", 10, storage=s)
        assert result["count"] == 1
        assert result["latest"]["close"] == 4

    @pytest.mark.asyncio
    async def test_from_storage_empty(self):
        s = MagicMock()
        s.query_klines = AsyncMock(return_value=[])
        result = await market_data_tools.get_kline_data(
            "BTCUSDT", "30m", 10, storage=s)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_from_provider(self):
        provider = MagicMock()
        std = MagicMock()
        std.symbol = "BTCUSDT"; std.interval = "30m"; std.open_time = 1
        std.open = 1.0; std.high = 2.0; std.low = 3.0; std.close = 4.0
        std.volume = 5.0; std.close_time = 6; std.quote_volume = 7.0
        std.trades = 1; std.taker_buy_base = 1.0; std.taker_buy_quote = 1.0
        std.is_final = True
        provider.get_klines = AsyncMock(return_value=[std])
        with patch.object(market_data_tools, "get_binance_provider",
                          new=AsyncMock(return_value=provider)):
            result = await market_data_tools.get_kline_data("BTCUSDT")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_provider_fail_legacy_fallback(self):
        provider = MagicMock()
        provider.get_klines = AsyncMock(side_effect=RuntimeError("down"))
        legacy = MagicMock()
        legacy.open_time = 1; legacy.open = 1.0; legacy.high = 2.0
        legacy.low = 3.0; legacy.close = 4.0; legacy.volume = 5.0
        with patch.object(market_data_tools, "get_binance_provider",
                          new=AsyncMock(return_value=provider)), \
             patch.object(market_data_tools, "_get_klines_legacy",
                          new=AsyncMock(return_value=[legacy])):
            result = await market_data_tools.get_kline_data("BTCUSDT")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_no_provider_legacy(self):
        legacy = MagicMock()
        legacy.open_time = 1; legacy.open = 1.0; legacy.high = 2.0
        legacy.low = 3.0; legacy.close = 4.0; legacy.volume = 5.0
        with patch.object(market_data_tools, "get_binance_provider",
                          new=AsyncMock(return_value=None)), \
             patch.object(market_data_tools, "_get_klines_legacy",
                          new=AsyncMock(return_value=[legacy])):
            result = await market_data_tools.get_kline_data("BTCUSDT")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_legacy_empty_error(self):
        with patch.object(market_data_tools, "get_binance_provider",
                          new=AsyncMock(return_value=None)), \
             patch.object(market_data_tools, "_get_klines_legacy",
                          new=AsyncMock(return_value=[])):
            result = await market_data_tools.get_kline_data("BTCUSDT")
        assert "error" in result


class TestBinanceProviderHelper:
    @pytest.mark.asyncio
    async def test_unavailable(self):
        with patch.object(market_data_tools, "PROVIDER_AVAILABLE", False):
            assert await market_data_tools.get_binance_provider() is None

    @pytest.mark.asyncio
    async def test_create_fail(self):
        market_data_tools._binance_provider = None
        with patch.object(market_data_tools, "PROVIDER_AVAILABLE", True), \
             patch.object(market_data_tools.ProviderFactory, "get_provider",
                          new=AsyncMock(side_effect=RuntimeError("x"))):
            assert await market_data_tools.get_binance_provider() is None

    @pytest.mark.asyncio
    async def test_success_and_cached(self):
        market_data_tools._binance_provider = None
        provider = MagicMock()
        with patch.object(market_data_tools, "PROVIDER_AVAILABLE", True), \
             patch.object(market_data_tools.ProviderFactory, "get_provider",
                          new=AsyncMock(return_value=provider)):
            p1 = await market_data_tools.get_binance_provider()
            p2 = await market_data_tools.get_binance_provider()
        assert p1 is provider and p2 is provider

    def test_convert_standard_to_legacy(self):
        from vibe_trading.data_sources.providers.models import StandardKline
        std = StandardKline(
            exchange="binance", symbol="BTCUSDT", interval="30m",
            open_time=1, open=1.0, high=2.0, low=3.0, close=4.0,
            volume=5.0, close_time=6, quote_volume=7.0, trades=1,
            taker_buy_base=1.0, taker_buy_quote=1.0, is_final=True)
        k = market_data_tools.convert_standard_to_legacy(std)
        assert k.symbol == "BTCUSDT"
        assert k.close == 4.0


class TestFundingAndInterest:
    @pytest.mark.asyncio
    async def test_get_funding_rate(self):
        client = MagicMock()
        client.rest._request = AsyncMock(return_value={
            "lastFundingRate": "0.0001", "nextFundingTime": 123,
            "markPrice": "50000", "indexPrice": "49999"})
        client.close = AsyncMock()
        with patch.object(market_data_tools, "BinanceClient",
                          return_value=client):
            result = await market_data_tools.get_funding_rate("BTCUSDT")
        assert result["funding_rate"] == 0.0001

    @pytest.mark.asyncio
    async def test_get_open_interest(self):
        client = MagicMock()
        client.rest._request = AsyncMock(return_value={
            "openInterest": "1234.5", "time": 999})
        client.close = AsyncMock()
        with patch.object(market_data_tools, "BinanceClient",
                          return_value=client):
            result = await market_data_tools.get_open_interest("BTCUSDT")
        assert result["open_interest"] == 1234.5
        assert result["timestamp"] == 999


class TestFundamentalTools:
    @pytest.fixture(autouse=True)
    def _mods(self):
        global fundamental_tools
        from vibe_trading.tools import fundamental_tools
        yield

    @pytest.mark.asyncio
    async def test_get_long_short_ratio(self):
        resp = MagicMock()
        resp.json = MagicMock(return_value=[{"longShortRatio": "1.5",
                                             "longAccount": "1.5",
                                             "shortAccount": "1.0",
                                             "timestamp": 1000}])
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=resp)
        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=client):
            result = await fundamental_tools.get_long_short_ratio("BTCUSDT")
        assert "long_short_ratio" in result

    @pytest.mark.asyncio
    async def test_get_taker_buy_sell(self):
        resp = MagicMock()
        resp.json = MagicMock(return_value=[{"buySellRatio": "2.0",
                                             "buyVol": "10", "sellVol": "5",
                                             "timestamp": 1000}])
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=resp)
        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=client):
            result = await fundamental_tools.get_taker_buy_sell_ratio("BTCUSDT")
        assert "taker_buy_sell_ratio" in result

    @pytest.mark.asyncio
    async def test_get_open_interest_fundamental(self):
        resp = MagicMock()
        resp.json = MagicMock(return_value=[
            {"sumOpenInterest": "500", "sumOpenInterestValue": "1000",
             "timestamp": 1000},
            {"sumOpenInterest": "400", "sumOpenInterestValue": "800",
             "timestamp": 900}])
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=resp)
        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=client):
            result = await fundamental_tools.get_open_interest("BTCUSDT")
        assert "open_interest" in result

    @pytest.mark.asyncio
    async def test_http_error_returns_error(self):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=RuntimeError("network"))
        with patch.object(fundamental_tools.httpx, "AsyncClient",
                          return_value=client):
            result = await fundamental_tools.get_long_short_ratio("BTCUSDT")
        assert "error" in result
