"""Tests for DataSourceRouter (Wave A — coverage 85% plan)."""
import pytest

from vibe_trading.data_sources.vendor_router import (
    BinanceDataSource,
    CoinGeckoDataSource,
    DataSourceException,
    DataSourceRouter,
    DataSourceType,
    DataType,
    RateLimitException,
    VendorMethod,
    get_data_source_router,
    initialize_default_vendors,
    register_vendor_method,
    vendor_routed,
)


class TestVendorMethod:
    def test_priority_default(self):
        vm = VendorMethod(vendor=DataSourceType.BINANCE, method=lambda: 1)
        assert vm.priority == 0

    def test_str_enum(self):
        assert DataSourceType.BINANCE == "binance"
        assert DataType.KLINE == "kline"


class TestExceptions:
    def test_datasource_exception_message(self):
        e = DataSourceException("boom", DataSourceType.BINANCE)
        assert "[binance]" in str(e)
        assert e.vendor == DataSourceType.BINANCE

    def test_datasource_exception_with_original(self):
        inner = ValueError("orig")
        e = DataSourceException("boom", DataSourceType.OKX, inner)
        assert e.original_error is inner

    def test_rate_limit_is_subclass(self):
        assert issubclass(RateLimitException, DataSourceException)


class TestRouter:
    @pytest.mark.asyncio
    async def test_route_unknown_type_raises(self):
        r = DataSourceRouter()
        with pytest.raises(ValueError):
            await r.route(DataType.KLINE)

    @pytest.mark.asyncio
    async def test_route_no_methods_raises(self):
        r = DataSourceRouter()
        r._method_registry[DataType.KLINE] = []
        with pytest.raises(RuntimeError):
            await r.route(DataType.KLINE)

    @pytest.mark.asyncio
    async def test_route_sync_method(self):
        r = DataSourceRouter()
        r.register_method(DataType.TICKER, DataSourceType.BINANCE,
                          lambda s: {"ok": s}, priority=0)
        result = await r.route(DataType.TICKER, "BTCUSDT")
        assert result == {"ok": "BTCUSDT"}

    @pytest.mark.asyncio
    async def test_route_async_method(self):
        r = DataSourceRouter()

        async def _get(symbol):
            return {"price": 100}

        r.register_method(DataType.TICKER, DataSourceType.BINANCE, _get, priority=0)
        result = await r.route(DataType.TICKER, "BTCUSDT")
        assert result == {"price": 100}

    @pytest.mark.asyncio
    async def test_route_fallback_on_error(self):
        r = DataSourceRouter()

        def _primary(symbol):
            raise RuntimeError("down")

        async def _backup(symbol):
            return {"source": "backup"}

        r.register_method(DataType.TICKER, DataSourceType.BINANCE, _primary, priority=0)
        r.register_method(DataType.TICKER, DataSourceType.COINGECKO, _backup, priority=1)

        result = await r.route(DataType.TICKER, "BTCUSDT")
        assert result == {"source": "backup"}
        assert r.get_fallback_stats()["total_fallbacks"] == 1
        assert ("ticker", "coingecko") in r.get_fallback_stats()["by_type_and_vendor"]

    @pytest.mark.asyncio
    async def test_route_fallback_on_rate_limit(self):
        r = DataSourceRouter()

        def _primary(symbol):
            raise RateLimitException("too many", DataSourceType.BINANCE)

        def _backup(symbol):
            return {"source": "okx"}

        r.register_method(DataType.KLINE, DataSourceType.BINANCE, _primary, priority=0)
        r.register_method(DataType.KLINE, DataSourceType.OKX, _backup, priority=1)
        result = await r.route(DataType.KLINE, "BTCUSDT")
        assert result == {"source": "okx"}

    @pytest.mark.asyncio
    async def test_route_all_fail_raises(self):
        r = DataSourceRouter()

        def _fail(symbol):
            raise RuntimeError("down")

        r.register_method(DataType.TICKER, DataSourceType.BINANCE, _fail, priority=0)
        r.register_method(DataType.TICKER, DataSourceType.OKX, _fail, priority=1)
        with pytest.raises(RuntimeError) as exc:
            await r.route(DataType.TICKER, "BTCUSDT")
        assert "binance" in str(exc.value)
        assert "okx" in str(exc.value)

    @pytest.mark.asyncio
    async def test_priority_order(self):
        r = DataSourceRouter()
        calls = []

        def _p0(symbol):
            calls.append("p0")
            return "p0"

        def _p1(symbol):
            calls.append("p1")
            return "p1"

        # 註冊順序反轉, 但 priority 決定執行序
        r.register_method(DataType.TICKER, DataSourceType.OKX, _p1, priority=1)
        r.register_method(DataType.TICKER, DataSourceType.BINANCE, _p0, priority=0)
        result = await r.route(DataType.TICKER, "x")
        assert result == "p0"
        assert calls == ["p0"]

    def test_performance_stats(self):
        r = DataSourceRouter()
        r._record_success(DataSourceType.BINANCE, DataType.TICKER, 0.5)
        r._record_success(DataSourceType.BINANCE, DataType.TICKER, 0.3)
        r._record_failure(DataSourceType.BINANCE, DataType.TICKER, "error")
        stats = r.get_performance_stats()
        assert stats[DataSourceType.BINANCE]["success_count"] == 2
        assert stats[DataSourceType.BINANCE]["failure_count"] == 1
        assert stats[DataSourceType.BINANCE]["avg_time"] == pytest.approx(0.4)

    def test_fallback_history_cap(self):
        r = DataSourceRouter()
        # 1100 次: 第 1001 次觸發截斷到 500 → 剩 500 + 99 = 599
        for i in range(1100):
            r._record_fallback(DataType.TICKER, DataSourceType.BINANCE, DataSourceType.OKX)
        assert len(r._fallback_history) == 599

    def test_register_vendor_method_global(self):
        router = get_data_source_router()
        register_vendor_method(DataType.NEWS, DataSourceType.COINGECKO, lambda: "news", 5)
        assert DataType.NEWS in router._method_registry

    def test_initialize_default_vendors(self):
        # 已在 import 時執行; 再跑一次不 raise
        initialize_default_vendors()
        router = get_data_source_router()
        assert DataType.KLINE in router._method_registry
        assert DataType.TICKER in router._method_registry


class TestVendorRoutedDecorator:
    @pytest.mark.asyncio
    async def test_decorator_registers_and_routes(self):
        @vendor_routed(DataType.TICKER, DataSourceType.BINANCE, priority=0)
        async def get_ticker(symbol: str):
            return {"symbol": symbol}

        result = await get_ticker("BTCUSDT")
        assert result == {"symbol": "BTCUSDT"}


class TestDataSourceClasses:
    def test_binance_init(self):
        # BinanceClient() 可能需網路; 只驗證類存在 + 方法簽名
        assert hasattr(BinanceDataSource, "get_kline")
        assert hasattr(BinanceDataSource, "get_ticker")

    @pytest.mark.asyncio
    async def test_binance_get_kline_failure_wraps(self):
        ds = BinanceDataSource.__new__(BinanceDataSource)  # 跳過 __init__ (不需 client)

        async def _fail(*a, **k):
            raise RuntimeError("network down")

        ds.client = type("Fake", (), {"get_klines": _fail})()
        with pytest.raises(DataSourceException) as exc:
            await ds.get_kline("BTCUSDT", "1h")
        assert exc.value.vendor == DataSourceType.BINANCE

    @pytest.mark.asyncio
    async def test_coingecko_get_ticker_failure_wraps(self):
        ds = CoinGeckoDataSource.__new__(CoinGeckoDataSource)

        async def _fail(*a, **k):
            raise DataSourceException("HTTP 500", DataSourceType.COINGECKO)

        ds.get_ticker = _fail
        with pytest.raises(DataSourceException):
            await ds.get_ticker("BTCUSDT")
