"""Tests for WebSocketManager (Wave D — coverage 85% plan).

策略: _handle_message 是純解析 (mock msg) — 測完整 Kline 解析 + 邊界;
subscribe/unsubscribe/stop/statistics 不需真實 socket.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.websocket_manager import WebSocketManager


@pytest.fixture
def ws():
    return WebSocketManager()


def _kline_msg(symbol: str = "BTCUSDT", interval: str = "30m", final: bool = True):
    return {
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "k": {
                "s": symbol, "t": 1700000000000, "T": 1700000001000,
                "o": "50000", "h": "50500", "l": "49900", "c": "50400",
                "v": "100.5", "q": "5000000", "n": 250,
                "V": "60.2", "Q": "3000000", "x": final,
            }
        },
    }


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_kline(self, ws):
        cb = MagicMock()
        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        assert "btcusdt@kline_30m" in ws._streams
        assert ws._streams["btcusdt@kline_30m"].callback is cb

    @pytest.mark.asyncio
    async def test_subscribe_duplicate_skips(self, ws):
        cb = MagicMock()
        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        await ws.subscribe_kline("BTCUSDT", "30m", cb)  # 已訂閱 → 跳過
        assert len(ws._streams) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, ws):
        await ws.subscribe_kline("BTCUSDT", "30m", MagicMock())
        await ws.unsubscribe_kline("BTCUSDT", "30m")
        assert "btcusdt@kline_30m" not in ws._streams

    @pytest.mark.asyncio
    async def test_unsubscribe_missing(self, ws):
        await ws.unsubscribe_kline("BTCUSDT", "30m")  # 不 raise


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_handle_final_kline_calls_callback(self, ws):
        cb = MagicMock()
        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        await ws._handle_message(_kline_msg())
        # callback 在背景 task 執行 — 等一瞬
        await asyncio_sleep(0.05)
        assert cb.called

    @pytest.mark.asyncio
    async def test_handle_non_final_no_callback(self, ws):
        cb = MagicMock()
        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        await ws._handle_message(_kline_msg(final=False))
        await asyncio_sleep(0.05)
        assert not cb.called

    @pytest.mark.asyncio
    async def test_handle_empty_msg(self, ws):
        await ws._handle_message({})  # 不 raise
        await ws._handle_message(None)  # 不 raise
        await ws._handle_message({"stream": "x"})  # 無 data

    @pytest.mark.asyncio
    async def test_handle_no_k_field(self, ws):
        await ws._handle_message({"stream": "x", "data": {}})  # 不 raise

    @pytest.mark.asyncio
    async def test_handle_async_callback(self, ws):
        async def cb(kline):
            pass

        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        await ws._handle_message(_kline_msg())
        await asyncio_sleep(0.05)  # 不 raise

    @pytest.mark.asyncio
    async def test_handle_callback_error_swallowed(self, ws):
        def cb(kline):
            raise RuntimeError("boom")

        await ws.subscribe_kline("BTCUSDT", "30m", cb)
        await ws._handle_message(_kline_msg())
        await asyncio_sleep(0.05)  # 錯誤被吞


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_no_streams(self, ws):
        await ws.start()  # 無訂閱 → 不 raise

    @pytest.mark.asyncio
    async def test_stop(self, ws):
        await ws.stop()  # 不 raise

    def test_is_running(self, ws):
        assert ws.is_running() is False
        ws._running = True
        assert ws.is_running() is True

    def test_get_active_streams(self, ws):
        ws._streams["a@kline_1m"] = MagicMock()
        assert ws.get_active_streams() == ["a@kline_1m"]

    def test_init(self):
        ws = WebSocketManager(api_key="k", api_secret="s", testnet=True)
        assert ws.testnet is True
        assert ws._max_reconnect_attempts == 5


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_client(self, ws):
        with patch("vibe_trading.websocket_manager.AsyncClient") as mock_client, \
             patch("vibe_trading.websocket_manager.BinanceSocketManager") as mock_bsm:
            await ws.initialize()
            mock_client.assert_called_once()
            mock_bsm.assert_called_once()
            assert ws._client is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, ws):
        ws._client = MagicMock()
        with patch("vibe_trading.websocket_manager.AsyncClient") as mock_client:
            await ws.initialize()
            mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_failure_raises(self, ws):
        with patch("vibe_trading.websocket_manager.AsyncClient",
                   side_effect=RuntimeError("conn refused")):
            with pytest.raises(RuntimeError):
                await ws.initialize()


def asyncio_sleep(sec):
    import asyncio
    return asyncio.sleep(sec)
