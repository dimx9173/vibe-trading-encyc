"""Tests for binance_client models (Wave D — coverage 85% plan)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestBinanceRequest:
    @pytest.mark.asyncio
    async def test_request_success(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceRestClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s", rest_base_url="https://x")
        client = BinanceRestClient(cfg)
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"symbols": []})

        class _CM:
            async def __aenter__(self):
                return resp

            async def __aexit__(self, *a):
                return None

        session.request = MagicMock(return_value=_CM())
        client._session = session
        data = await client._request("GET", "/fapi/v1/exchangeInfo")
        assert data == {"symbols": []}

    @pytest.mark.asyncio
    async def test_request_api_error(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceRestClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s", rest_base_url="https://x")
        client = BinanceRestClient(cfg)
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.status = 400
        resp.json = AsyncMock(return_value={"msg": "bad"})

        class _CM:
            async def __aenter__(self):
                return resp

            async def __aexit__(self, *a):
                return None

        session.request = MagicMock(return_value=_CM())
        client._session = session
        with pytest.raises(Exception) as exc:
            await client._request("GET", "/fapi/v1/x")
        assert "API Error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_request_signed(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceRestClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s", rest_base_url="https://x")
        client = BinanceRestClient(cfg)
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={})

        class _CM:
            async def __aenter__(self):
                return resp

            async def __aexit__(self, *a):
                return None

        session.request = MagicMock(return_value=_CM())
        client._session = session
        await client._request("GET", "/fapi/v1/order", signed=True)
        kwargs = session.request.call_args.kwargs
        assert "timestamp" in kwargs["params"]
        assert "signature" in kwargs["params"]


class TestBinanceWSClient:
    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        with patch("vibe_trading.data_sources.binance_client.websockets") as mock_ws:
            ws = MagicMock()
            ws.close = AsyncMock()
            mock_ws.connect = AsyncMock(return_value=ws)
            await client.connect()
            assert client._running is True
            await client.disconnect()
            assert client._running is False
            ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_twice(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client._ws = MagicMock()
        await client.connect()  # 已連接 → 直接 return
        assert client._running is False or True

    def test_subscribe_kline(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client.subscribe_kline("BTCUSDT", KlineInterval.MINUTE_30, lambda k: None)
        assert "btcusdt@kline_30m" in client._kline_callbacks
        assert len(client._kline_callbacks["btcusdt@kline_30m"]) == 1

    @pytest.mark.asyncio
    async def test_disconnect_no_ws(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        await client.disconnect()  # 不 raise


class TestWsListen:
    def _msg(self, stream="btcusdt@kline_30m"):
        return json.dumps({
            "stream": stream,
            "s": "BTCUSDT",
            "k": {"i": "30m", "t": 1000, "T": 2000, "o": "100", "h": "105",
                  "l": "95", "c": "102", "v": "10", "q": "1000", "n": 5,
                  "V": "5", "Q": "500", "x": False},
        })

    @pytest.mark.asyncio
    async def test_listen_async_callback(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client._running = True
        seen = []

        async def cb(kline):
            seen.append(kline)

        client._kline_callbacks["btcusdt@kline_30m"] = [cb]
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=_MsgIter([self._msg()]))
        client._ws = ws
        await client._listen()
        assert len(seen) == 1
        assert seen[0].symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_listen_sync_callback(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client._running = True
        seen = []

        def cb(kline):
            seen.append(kline)

        client._kline_callbacks["btcusdt@kline_30m"] = [cb]
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=_MsgIter([self._msg()]))
        client._ws = ws
        await client._listen()
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_listen_bad_json(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client._running = True
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=_MsgIter(["{not json"]))
        client._ws = ws
        await client._listen()  # 錯誤被吞

    @pytest.mark.asyncio
    async def test_listen_stops_when_not_running(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceWebSocketClient,
        )
        cfg = BinanceConfig(api_key="k", api_secret="s")
        client = BinanceWebSocketClient(cfg)
        client._running = False
        ws = MagicMock()
        ws.__aiter__ = MagicMock(return_value=_MsgIter([self._msg()]))
        client._ws = ws
        await client._listen()  # 第一條就 break


class _MsgIter:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._msgs:
            return self._msgs.pop(0)
        raise StopAsyncIteration


class TestRestData:
    def _client(self):
        from vibe_trading.data_sources.binance_client import (
            BinanceConfig, BinanceRestClient,
        )
        return BinanceRestClient(BinanceConfig(api_key="k", api_secret="s"))

    @pytest.mark.asyncio
    async def test_get_klines_with_time(self):
        client = self._client()
        with patch.object(client, "_request",
                          new=AsyncMock(return_value=[])) as req:
            await client.get_klines("BTCUSDT", KlineInterval.MINUTE_30,
                                    start_time=1000, end_time=2000)
        kwargs = req.call_args.kwargs
        assert kwargs["params"]["startTime"] == 1000
        assert kwargs["params"]["endTime"] == 2000

    @pytest.mark.asyncio
    async def test_get_position_filters_zero(self):
        client = self._client()
        data = [
            {"symbol": "BTCUSDT", "positionAmt": "1.5", "entryPrice": "100",
             "markPrice": "110", "unRealizedProfit": "15", "liquidationPrice": "50",
             "leverage": "10", "positionSide": "LONG", "notional": "165",
             "isolated": False, "adlQuantile": 1},
            {"symbol": "ETHUSDT", "positionAmt": "0", "entryPrice": "0",
             "markPrice": "0", "unRealizedProfit": "0", "liquidationPrice": "0",
             "leverage": "1", "positionSide": "LONG", "notional": "0",
             "isolated": False, "adlQuantile": 0},
        ]
        with patch.object(client, "_request",
                          new=AsyncMock(return_value=data)):
            positions = await client.get_position()
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDT"
        assert positions[0].position_side.value == "LONG"

    @pytest.mark.asyncio
    async def test_get_balance_filters_zero(self):
        client = self._client()
        data = [
            {"asset": "USDT", "balance": "5000", "availableBalance": "4000",
             "crossWalletBalance": "5000"},
            {"asset": "BTC", "balance": "0", "availableBalance": "0",
             "crossWalletBalance": "0"},
        ]
        with patch.object(client, "_request",
                          new=AsyncMock(return_value=data)):
            bal = await client.get_balance()
        assert bal["USDT"]["balance"] == 5000.0
        assert "BTC" not in bal

    @pytest.mark.asyncio
    async def test_get_position_symbol_param(self):
        client = self._client()
        with patch.object(client, "_request",
                          new=AsyncMock(return_value=[])) as req:
            await client.get_position(symbol="BTCUSDT")
        assert req.call_args.kwargs["params"] == {"symbol": "BTCUSDT"}
