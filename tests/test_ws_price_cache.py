"""Tests for WebSocketPriceCache (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, patch

import pytest

from vibe_trading.data_sources.ws_price_cache import WebSocketPriceCache


class TestPriceCache:
    @pytest.mark.asyncio
    async def test_process_price_update(self):
        c = WebSocketPriceCache()
        await c._process_price_update("BTCUSDT", 50000.0)
        assert await c.get_price("BTCUSDT") == 50000.0
        assert await c.get_price("btcusdt") == 50000.0  # 大小寫不敏感

    @pytest.mark.asyncio
    async def test_get_price_missing(self):
        c = WebSocketPriceCache()
        assert await c.get_price("NOPE") is None

    @pytest.mark.asyncio
    async def test_on_price_update(self):
        c = WebSocketPriceCache()
        with patch.object(c, "_process_price_update", new=AsyncMock()) as mock_proc:
            c._on_price_update({"s": "BTCUSDT", "c": "51000"})
        mock_proc.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_price_update_invalid(self):
        c = WebSocketPriceCache()
        c._on_price_update({})  # 不 raise
        c._on_price_update({"s": "", "c": "0"})  # symbol 空 → 跳過

    @pytest.mark.asyncio
    async def test_fallback_used(self):
        c = WebSocketPriceCache()
        async def fallback():
            return 48000.0
        price = await c.get_price_with_fallback("BTCUSDT", fallback)
        assert price == 48000.0
        # fallback 更新 cache
        assert await c.get_price("BTCUSDT") == 48000.0

    @pytest.mark.asyncio
    async def test_cache_hit_no_fallback(self):
        c = WebSocketPriceCache()
        await c._process_price_update("BTCUSDT", 50000.0)
        called = []

        async def fallback():
            called.append(1)
            return 99999.0

        assert await c.get_price_with_fallback("BTCUSDT", fallback) == 50000.0
        assert called == []

    @pytest.mark.asyncio
    async def test_fallback_error(self):
        c = WebSocketPriceCache()
        async def fallback():
            raise RuntimeError("down")
        assert await c.get_price_with_fallback("BTCUSDT", fallback) is None

    @pytest.mark.asyncio
    async def test_no_fallback(self):
        c = WebSocketPriceCache()
        assert await c.get_price_with_fallback("BTCUSDT") is None


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_notified(self):
        c = WebSocketPriceCache()
        received = []

        async def cb(symbol, price):
            received.append((symbol, price))

        c.subscribe("BTCUSDT", cb)
        await c._process_price_update("BTCUSDT", 50000.0)
        assert received == [("BTCUSDT", 50000.0)]

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        c = WebSocketPriceCache()

        async def cb(symbol, price):
            pass

        c.subscribe("BTCUSDT", cb)
        c.unsubscribe("BTCUSDT", cb)
        await c._process_price_update("BTCUSDT", 1.0)  # 無 callback → 不 raise

    @pytest.mark.asyncio
    async def test_callback_error_swallowed(self):
        c = WebSocketPriceCache()

        async def bad_cb(symbol, price):
            raise RuntimeError("boom")

        async def good_cb(symbol, price):
            pass

        c.subscribe("BTCUSDT", bad_cb)
        c.subscribe("BTCUSDT", good_cb)
        await c._process_price_update("BTCUSDT", 1.0)  # 錯誤被吞


class TestCacheAge:
    @pytest.mark.asyncio
    async def test_get_cache_age(self):
        c = WebSocketPriceCache()
        assert await c.get_cache_age("NOPE") is None
        await c._process_price_update("BTCUSDT", 1.0)
        age = await c.get_cache_age("BTCUSDT")
        assert age is not None and age >= 0

    @pytest.mark.asyncio
    async def test_is_fresh(self):
        c = WebSocketPriceCache()
        assert await c.is_fresh("BTCUSDT") is False  # 無資料
        await c._process_price_update("BTCUSDT", 1.0)
        assert await c.is_fresh("BTCUSDT") is True


class TestStats:
    def test_get_stats(self):
        c = WebSocketPriceCache()
        stats = c.get_stats()
        assert stats["count"] == 0
        assert stats["running"] is False
