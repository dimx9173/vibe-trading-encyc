"""Tests for BinanceProvider — Wave D116."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.data_sources.exchange_config import (
    BinanceExchangeConfig,
    ExchangeType,
)
from vibe_trading.data_sources.providers.binance_provider import BinanceProvider
from vibe_trading.data_sources.binance_client import Kline, KlineInterval


def _provider():
    p = BinanceProvider.__new__(BinanceProvider)
    p._client = MagicMock()
    p._status = MagicMock()
    p._status.connected = False
    p._status.last_error = None
    p._subscribed_streams = set()
    return p


class TestBinanceProvider:
    @pytest.mark.asyncio
    async def test_connect(self):
        p = _provider()
        p._client.ws.connect = AsyncMock()
        await p.connect()
        assert p._status.connected is True

    @pytest.mark.asyncio
    async def test_connect_error(self):
        p = _provider()
        p._client.ws.connect = AsyncMock(side_effect=RuntimeError("down"))
        with pytest.raises(RuntimeError):
            await p.connect()
        assert p._status.connected is False
        assert p._status.last_error == "down"

    @pytest.mark.asyncio
    async def test_disconnect(self):
        p = _provider()
        p._client.close = AsyncMock()
        await p.disconnect()
        assert p._status.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_error(self):
        p = _provider()
        p._client.close = AsyncMock(side_effect=RuntimeError("x"))
        await p.disconnect()  # 錯誤被吞

    def test_exchange_name(self):
        p = _provider()
        assert p.exchange_name == "binance"

    @pytest.mark.asyncio
    async def test_get_klines(self):
        p = _provider()
        p._client.rest.get_klines = AsyncMock(return_value=[
            [1000, "100", "105", "95", "102", "10", "1600", "1000", "5",
             "5", "500"],
        ])
        klines = await p.get_klines("BTCUSDT", "30m")
        assert len(klines) == 1
        assert klines[0].symbol == "BTCUSDT"
        assert klines[0].close == 102.0

    @pytest.mark.asyncio
    async def test_get_klines_invalid_interval(self):
        p = _provider()
        p._client.rest.get_klines = AsyncMock(return_value=[])
        klines = await p.get_klines("BTCUSDT", "bogus")
        assert klines == []
        # 驗證 fallback 到 30m
        interval_arg = p._client.rest.get_klines.call_args.kwargs["interval"]
        assert interval_arg == KlineInterval.MINUTE_30

    @pytest.mark.asyncio
    async def test_get_klines_passes_time(self):
        p = _provider()
        p._client.rest.get_klines = AsyncMock(return_value=[])
        await p.get_klines("BTCUSDT", "30m", start_time=100, end_time=200)
        kwargs = p._client.rest.get_klines.call_args.kwargs
        assert kwargs["start_time"] == 100
        assert kwargs["end_time"] == 200

    @pytest.mark.asyncio
    async def test_get_ticker(self):
        p = _provider()
        p._client.rest._request = AsyncMock(return_value={
            "symbol": "BTCUSDT", "priceChange": "1", "priceChangePercent": "2",
            "highPrice": "105", "lowPrice": "95", "volume": "10",
            "quoteVolume": "1000", "openPrice": "100", "lastPrice": "102",
            "closeTime": 1600,
        })
        ticker = await p.get_ticker("BTCUSDT")
        assert ticker.exchange == "binance"
        assert ticker.close == 102.0

    @pytest.mark.asyncio
    async def test_get_orderbook(self):
        p = _provider()
        p._client.rest._request = AsyncMock(return_value={
            "bids": [["100", "1"], ["99", "2"]],
            "asks": [["101", "1"], ["102", "2"]],
            "lastUpdateId": 42,
        })
        ob = await p.get_orderbook("BTCUSDT", limit=1)
        assert len(ob.bids) == 1
        assert ob.bids[0].price == 100.0
        assert ob.asks[0].price == 101.0

    @pytest.mark.asyncio
    async def test_get_current_price(self):
        p = _provider()
        p._client.rest._request = AsyncMock(
            return_value={"price": "50000.5"})
        assert await p.get_current_price("BTCUSDT") == 50000.5

    @pytest.mark.asyncio
    async def test_subscribe_klines(self):
        p = _provider()
        p._client.ws.subscribe_kline = MagicMock()
        await p.subscribe_klines("BTCUSDT", "30m", lambda k: None)
        assert "BTCUSDT@30m" in p._subscribed_streams
        p._client.ws.subscribe_kline.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_invalid_interval(self):
        p = _provider()
        p._client.ws.subscribe_kline = MagicMock()
        await p.subscribe_klines("BTCUSDT", "bogus", lambda k: None)
        interval_arg = p._client.ws.subscribe_kline.call_args.kwargs["interval"]
        assert interval_arg == KlineInterval.MINUTE_30

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        p = _provider()
        p._subscribed_streams.add("BTCUSDT@30m")
        await p.unsubscribe_klines("BTCUSDT", "30m")
        assert "BTCUSDT@30m" not in p._subscribed_streams

    def test_convert_raw_kline(self):
        p = _provider()
        k = p._convert_raw_kline(
            [1000, "100", "105", "95", "102", "10", "1600", "1000", "5",
             "5", "500"], "BTCUSDT", "30m")
        assert k.open_time == 1000
        assert k.close_time == 1600
        assert k.trades == 5
        assert k.is_final is True

    def test_convert_kline(self):
        p = _provider()
        kline = Kline(
            symbol="BTCUSDT", interval="30m", open_time=1000, open=100.0,
            high=105.0, low=95.0, close=102.0, volume=10.0, close_time=1600,
            quote_volume=1000.0, trades=5, taker_buy_base=5.0,
            taker_buy_quote=500.0, is_final=True)
        k = p._convert_kline(kline, "BTCUSDT", "30m")
        assert k.symbol == "BTCUSDT"
        assert k.close == 102.0
