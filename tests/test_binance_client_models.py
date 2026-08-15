"""Tests for binance_client models (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.data_sources.binance_client import (
    Kline,
    KlineInterval,
    Order,
    OrderSide,
    OrderType,
    PositionSide,
    SymbolFilters,
)


class TestKline:
    def test_from_stream(self):
        k = Kline.from_stream({
            "s": "BTCUSDT", "k": {
                "i": "30m", "t": 1700000000000, "T": 1700000001000,
                "o": "50000", "h": "50500", "l": "49900", "c": "50400",
                "v": "100.5", "q": "5000000", "n": 250,
                "V": "60.2", "Q": "3000000", "x": True,
            },
        })
        assert k.symbol == "BTCUSDT"
        assert k.close == 50400.0
        assert k.trades == 250
        assert k.taker_buy_base == 60.2
        assert k.is_final is True

    def test_from_rest(self):
        k = Kline.from_rest([
            1700000000000, "50000", "50500", "49900", "50400",
            "100.5", 1700000001000, "5000000", 250, "60.2", "3000000",
        ])
        assert k.open_time == 1700000000000
        assert k.high == 50500.0
        assert k.is_final is True
        assert k.symbol == ""

    def test_datetime_properties(self):
        k = Kline.from_rest([1700000000000, "1", "1", "1", "1", "1", 1700000001000,
                             "1", 0, "0", "0"])
        assert k.open_datetime is not None
        assert k.close_datetime is not None


class TestSymbolFilters:
    def test_from_exchange_symbol(self):
        sd = {
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001",
                 "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }
        f = SymbolFilters.from_exchange_symbol(sd)
        assert f.symbol == "BTCUSDT"
        assert f.tick_size == 0.10
        assert f.step_size == 0.001
        assert f.min_notional == 5.0

    def test_from_exchange_symbol_market_lot(self):
        sd = {
            "symbol": "ETHUSDT",
            "filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.01"},
            ],
        }
        f = SymbolFilters.from_exchange_symbol(sd)
        assert f.step_size == 0.01

    def test_from_exchange_symbol_empty(self):
        f = SymbolFilters.from_exchange_symbol({"symbol": "X", "filters": []})
        assert f.tick_size == 0.0
        assert f.min_qty == 0.0


class TestEnums:
    def test_interval_values(self):
        assert KlineInterval.MINUTE_30 == "30m"

    def test_order_side(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_type(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"

    def test_position_side(self):
        assert PositionSide.LONG.value == "LONG"
        assert PositionSide.SHORT.value == "SHORT"


class TestOrderModel:
    def test_order_defaults(self):
        o = Order(
            symbol="BTCUSDT", order_id=1, client_order_id="c1",
            side=OrderSide.BUY, order_type=OrderType.MARKET,
            position_side=PositionSide.LONG, quantity=0.1,
        )
        assert o.symbol == "BTCUSDT"
        assert o.price is None
        assert o.status == ""


class TestBinanceRestClient:
    @pytest.mark.asyncio
    async def test_sign(self):
        from vibe_trading.data_sources.binance_client import BinanceRestClient, BinanceConfig
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceRestClient(cfg)
        signed = client._sign({"symbol": "BTCUSDT"})
        assert "signature" in signed
        assert signed["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_close(self):
        from vibe_trading.data_sources.binance_client import BinanceRestClient, BinanceConfig
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceRestClient(cfg)
        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        client._session = session
        await client.close()
        session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_exchange_info(self):
        from vibe_trading.data_sources.binance_client import BinanceRestClient, BinanceConfig
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceRestClient(cfg)
        client._request = AsyncMock(return_value={"symbols": [{"symbol": "BTCUSDT"}]})
        info = await client.get_exchange_info()
        assert "symbols" in info

    @pytest.mark.asyncio
    async def test_get_symbol_filters(self):
        from vibe_trading.data_sources.binance_client import BinanceRestClient, BinanceConfig
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceRestClient(cfg)
        client.get_exchange_info = AsyncMock(return_value={"symbols": [{
            "symbol": "BTCUSDT",
            "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.1"}],
        }]})
        filters = await client.get_symbol_filters()
        assert "BTCUSDT" in filters
        assert filters["BTCUSDT"].tick_size == 0.1
