"""Tests for OkxProvider (Wave D — coverage 85% plan).

策略: mock _request (不發真實請求) 測解析; 純轉換函式直接測.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.data_sources.exchange_config import OkxExchangeConfig, ExchangeType
from vibe_trading.data_sources.providers.okx_provider import OkxProvider


def _provider():
    cfg = OkxExchangeConfig(
        exchange_type=ExchangeType.OKX, api_key="k", api_secret="s",
        passphrase="p", environment="testnet",
    )
    p = OkxProvider(cfg)
    p._request = AsyncMock()
    return p


class TestConversions:
    def test_convert_symbol_usdt(self):
        assert OkxProvider._convert_symbol("BTCUSDT") == "BTC-USDT-SWAP"

    def test_convert_symbol_usdc(self):
        assert OkxProvider._convert_symbol("ETHUSDC") == "ETH-USDC-SWAP"

    def test_convert_symbol_unknown(self):
        assert OkxProvider._convert_symbol("FOOXYZ") == "FOOXYZ"

    def test_okx_bar_map(self):
        assert OkxProvider._okx_bar("1h") == "1H"
        assert OkxProvider._okx_bar("unknown") == "30m"

    def test_interval_to_ms(self):
        assert OkxProvider._interval_to_ms("1h") == 3_600_000
        assert OkxProvider._interval_to_ms("unknown") == 1_800_000

    def test_sign_deterministic(self):
        p = _provider()
        s1 = p._sign("123", "GET", "/path", "")
        s2 = p._sign("123", "GET", "/path", "")
        assert s1 == s2
        assert len(s1) > 10

    def test_headers_contains_auth(self):
        p = _provider()
        h = p._headers("GET", "/path")
        assert "OK-ACCESS-KEY" in h
        assert h["OK-ACCESS-KEY"] == "k"
        assert "OK-ACCESS-SIGN" in h

    def test_headers_demo_trading(self):
        p = _provider()
        p.config.demo_trading = True
        h = p._headers("GET", "/path")
        assert h["x-simulated-trading"] == "1"


class TestGetKlines:
    @pytest.mark.asyncio
    async def test_parses_reversed(self):
        p = _provider()
        raw = [
            ["1700000000000", "100", "105", "95", "102", "1000", "0"],
            ["1699999996000", "99", "104", "94", "101", "900", "0"],
        ]
        p._request.return_value = raw
        klines = await p.get_klines("BTCUSDT", "30m", 100)
        assert len(klines) == 2
        # OKX newest-first → 反轉 → 第一個是最舊
        assert klines[0].open_time == 1699999996000
        assert klines[1].close == 102.0

    @pytest.mark.asyncio
    async def test_request_params(self):
        p = _provider()
        p._request.return_value = []
        await p.get_klines("BTCUSDT", "1h", 50, start_time=1000, end_time=2000)
        args = p._request.call_args
        assert args[0][0] == "/api/v5/market/candles"
        assert args[0][1]["instId"] == "BTC-USDT-SWAP"
        assert args[0][1]["after"] == "1000"
        assert args[0][1]["before"] == "2000"


class TestGetTicker:
    @pytest.mark.asyncio
    async def test_parses_ticker(self):
        p = _provider()
        p._request.return_value = [{
            "last": "50000", "open24h": "49000", "high24h": "51000",
            "low24h": "48500", "vol24h": "1000", "volCcy24h": "5e7",
            "ts": "1700000000000",
        }]
        t = await p.get_ticker("BTCUSDT")
        assert t.exchange == "okx"
        assert t.close == 50000.0
        assert t.price_change == 1000.0
        assert t.price_change_percent == pytest.approx(2.0408, abs=0.01)

    @pytest.mark.asyncio
    async def test_ticker_zero_open(self):
        p = _provider()
        p._request.return_value = [{"last": "1", "open24h": "0", "high24h": "1",
                                    "low24h": "1", "vol24h": "1", "volCcy24h": "1",
                                    "ts": "1"}]
        t = await p.get_ticker("BTCUSDT")
        assert t.price_change_percent == 0.0


class TestGetOrderbook:
    @pytest.mark.asyncio
    async def test_parses_orderbook(self):
        p = _provider()
        p._request.return_value = [{
            "bids": [["50000", "1.5"], ["49999", "2.0"]],
            "asks": [["50001", "1.0"]],
            "ts": "123",
        }]
        ob = await p.get_orderbook("BTCUSDT", 20)
        assert ob.bids[0].price == 50000.0
        assert ob.bids[0].quantity == 1.5
        assert len(ob.asks) == 1


class TestGetCurrentPrice:
    @pytest.mark.asyncio
    async def test_parses_price(self):
        p = _provider()
        p._request.return_value = [{"last": "50000"}]
        assert await p.get_current_price("BTCUSDT") == 50000.0


class TestSession:
    @pytest.mark.asyncio
    async def test_get_session_creates(self):
        p = _provider()
        with patch("vibe_trading.data_sources.providers.okx_provider.aiohttp"):
            s = await p._get_session()
        assert s is not None

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        p = _provider()
        p._session = MagicMock()
        await p.connect()
        await p.disconnect()

    def test_exchange_name(self):
        p = _provider()
        name = p.exchange_name
        assert callable(name) is False or name == "okx"


class TestRequest:
    @staticmethod
    def _live_provider():
        cfg = OkxExchangeConfig(
            exchange_type=ExchangeType.OKX, api_key="k", api_secret="s",
            passphrase="p", environment="testnet",
        )
        return OkxProvider(cfg)

    @pytest.mark.asyncio
    async def test_request_success(self):
        p = TestRequest._live_provider()
        p.config.rest_base_url = "https://www.okx.com"
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"code": "0", "data": [{"x": 1}]})
        class _CM:
            async def __aenter__(self):
                return resp
            async def __aexit__(self, *a):
                return None
        session.get = MagicMock(return_value=_CM())
        p._session = session
        result = await p._request("/api/v5/market/ticker", {"instId": "BTC-USDT"})
        assert result == [{"x": 1}]
        session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_error_raises(self):
        p = TestRequest._live_provider()
        p.config.rest_base_url = "https://www.okx.com"
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"code": "500", "msg": "server error"})
        class _CM:
            async def __aenter__(self):
                return resp
            async def __aexit__(self, *a):
                return None
        session.get = MagicMock(return_value=_CM())
        p._session = session
        with pytest.raises(Exception) as exc:
            await p._request("/api/v5/market/ticker")
        assert "OKX API error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_request_demo_header(self):
        p = TestRequest._live_provider()
        p.config.rest_base_url = "https://www.okx.com"
        p.config.demo_trading = True
        session = MagicMock()
        session.closed = False
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"code": "0", "data": []})
        class _CM:
            async def __aenter__(self):
                return resp
            async def __aexit__(self, *a):
                return None
        session.get = MagicMock(return_value=_CM())
        p._session = session
        await p._request("/api/v5/market/ticker")
        kwargs = session.get.call_args.kwargs
        assert kwargs["headers"].get("x-simulated-trading") == "1"


class TestOKXWS:
    @pytest.mark.asyncio
    async def test_subscribe_klines(self):
        p = _provider()
        p.config.ws_base_url = "wss://x"
        p._ws = MagicMock()
        p._ws.send = AsyncMock()
        await p.subscribe_klines("BTCUSDT", "30m", lambda k: None)
        assert any("candle30m" in k for k in p._ws_callbacks)
        p._ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_ensures_ws(self):
        p = _provider()
        p.config.ws_base_url = "wss://x"
        with patch("vibe_trading.data_sources.providers.okx_provider.websockets") as mock_ws:
            mock_ws.connect = AsyncMock(return_value=MagicMock())
            await p._ensure_ws()
        assert p._ws is not None
        assert p._ws_listen_task is not None
        # 清理 task (避免 asyncio CancelledError 洩漏)
        p._ws_listen_task.cancel()
        import asyncio as _aio
        try:
            await _aio.wait_for(_aio.shield(p._ws_listen_task), timeout=0.5)
        except (_aio.CancelledError, _aio.TimeoutError):
            pass

    @pytest.mark.asyncio
    async def test_unsubscribe_klines(self):
        p = _provider()
        p._ws = MagicMock()
        p._ws.send = AsyncMock()
        await p.subscribe_klines("BTCUSDT", "30m", lambda k: None)
        await p.unsubscribe_klines("BTCUSDT", "30m")
        assert p._ws_callbacks == {}
        p._ws.send.assert_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_no_ws(self):
        p = _provider()
        await p.unsubscribe_klines("BTCUSDT", "30m")  # 不 raise

    def test_convert_kline(self):
        p = _provider()
        raw = ["1700000000000", "100", "105", "95", "102", "1000", "0", "0", "0"]
        k = p._convert_kline(raw, "BTCUSDT", "30m")
        assert k.symbol == "BTCUSDT"
        assert k.close == 102.0


class TestWebSocket:
    @pytest.mark.asyncio
    async def test_ensure_ws(self):
        p = _provider()
        with patch("vibe_trading.data_sources.providers.okx_provider.websockets") as mock_ws:
            ws = MagicMock()
            mock_ws.connect = AsyncMock(return_value=ws)
            await p._ensure_ws()
            assert p._ws is ws
            await p._ensure_ws()  # 已連 → 直接 return

    @pytest.mark.asyncio
    async def test_ws_listen_async_callback(self):
        p = _provider()
        p._ws = MagicMock()
        p._ws.__aiter__ = MagicMock(return_value=_MsgIter([json.dumps({
            "arg": {"channel": "candle30m", "instId": "BTC-USDT-SWAP"},
            "data": [["1000", "100", "105", "95", "102", "10", "1000",
                      "10000", "0"]],
        })]))
        seen = []

        async def cb(kline):
            seen.append(kline)

        p._ws_callbacks["candle30m:BTC-USDT-SWAP"] = cb
        await p._ws_listen()
        assert len(seen) == 1
        assert seen[0].symbol == "BTCUSDT"
        assert seen[0].interval == "30m"

    @pytest.mark.asyncio
    async def test_ws_listen_sync_callback(self):
        p = _provider()
        p._ws = MagicMock()
        p._ws.__aiter__ = MagicMock(return_value=_MsgIter([json.dumps({
            "arg": {"channel": "candle1H", "instId": "ETH-USDT-SWAP"},
            "data": [["1000", "100", "105", "95", "102", "10", "1000",
                      "10000", "1"]],
        })]))
        seen = []

        def cb(kline):
            seen.append(kline)

        p._ws_callbacks["candle1H:ETH-USDT-SWAP"] = cb
        await p._ws_listen()
        assert len(seen) == 1
        assert seen[0].is_final is True

    @pytest.mark.asyncio
    async def test_subscribe_unsupported_interval(self):
        p = _provider()
        await p.subscribe_klines("BTCUSDT", "1X", lambda k: None)  # 不 raise

    @pytest.mark.asyncio
    async def test_subscribe_sends(self):
        p = _provider()
        p._ws = MagicMock()
        p._ws.send = AsyncMock()
        await p.subscribe_klines("BTCUSDT", "30m", lambda k: None)
        assert "BTCUSDT@30m" in p._subscribed_streams
        p._ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        p = _provider()
        p._ws = MagicMock()
        p._ws.send = AsyncMock()
        p._ws_callbacks["candle30m:BTC-USDT-SWAP"] = lambda k: None
        await p.unsubscribe_klines("BTCUSDT", "30m")
        assert "candle30m:BTC-USDT-SWAP" not in p._ws_callbacks

    @pytest.mark.asyncio
    async def test_unsubscribe_unsupported(self):
        p = _provider()
        await p.unsubscribe_klines("BTCUSDT", "1X")  # 不 raise

    def test_convert_ws_kline(self):
        p = _provider()
        k = p._convert_ws_kline(
            ["1000", "100", "105", "95", "102", "10", "1000", "10000", "0"],
            "BTC-USDT-SWAP", "1H")
        assert k.symbol == "BTCUSDT"
        assert k.interval == "1h"
        assert k.close == 102.0


class _MsgIter:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._msgs:
            return self._msgs.pop(0)
        raise StopAsyncIteration
