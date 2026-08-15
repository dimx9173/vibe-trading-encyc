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
            result = await market_data_tools.get_current_price("BTCUSDT", storage=s)
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
