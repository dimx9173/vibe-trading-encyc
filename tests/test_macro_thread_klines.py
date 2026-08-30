import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from vibe_trading.threads.macro_thread import MacroAnalysisThread


def _thread(kline_storage=None, interval="30m", lookback=24):
    t = MacroAnalysisThread.__new__(MacroAnalysisThread)
    t.symbol = "BTCUSDT"
    t.interval_seconds = 7200
    t.storage = MagicMock()
    t.kline_storage = kline_storage
    t.kline_lookback_hours = lookback
    t.kline_interval = interval
    t._agent = MagicMock()
    t._tool_context = MagicMock()
    t._running = False
    t._task = None
    t._total_runs = 0
    t._successful_runs = 0
    t._failed_runs = 0
    t._last_run_time = None
    return t


def _make_row(i):
    return SimpleNamespace(
        open_time=1000 + i * 1800000,
        open=50000 + i,
        high=50100 + i,
        low=49900 + i,
        close=50050 + i,
        volume=100 + i,
        close_time=0,
        quote_volume=0,
        trades=0,
        taker_buy_base=0,
        taker_buy_quote=0,
        is_final=True,
        symbol="BTCUSDT",
        interval="30m",
    )


class TestIntervalToMinutes:
    def test_known_mappings(self):
        t = _thread()
        assert t._interval_to_minutes("30m") == 30
        assert t._interval_to_minutes("1h") == 60
        assert t._interval_to_minutes("1d") == 1440

    def test_unknown_defaults_to_30(self):
        t = _thread()
        assert t._interval_to_minutes("unknown") == 30
        assert t._interval_to_minutes("") == 30


class TestCollectKlines24h:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_storage(self):
        t = _thread(kline_storage=None)
        assert await t._collect_klines_24h() is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self):
        storage = MagicMock()
        storage.query_klines = AsyncMock(return_value=[])
        t = _thread(kline_storage=storage)
        assert await t._collect_klines_24h() is None

    @pytest.mark.asyncio
    async def test_returns_compact_dicts_48_rows(self):
        rows = [_make_row(i) for i in range(48)]
        storage = MagicMock()
        storage.query_klines = AsyncMock(return_value=rows)
        t = _thread(kline_storage=storage, interval="30m", lookback=24)
        result = await t._collect_klines_24h()
        assert result is not None
        assert len(result) == 48
        assert set(result[0].keys()) == {"t", "o", "h", "l", "c", "v"}
        assert result[0]["t"] == 1000
        assert result[0]["o"] == 50000.0
        storage.query_klines.assert_called_once()
        q = storage.query_klines.call_args.args[0]
        assert q.limit == 48
        assert q.symbol == "BTCUSDT"
        assert q.interval == "30m"

    @pytest.mark.asyncio
    async def test_limit_calculation_1h(self):
        rows = [_make_row(i) for i in range(24)]
        storage = MagicMock()
        storage.query_klines = AsyncMock(return_value=rows)
        t = _thread(kline_storage=storage, interval="1h", lookback=24)
        result = await t._collect_klines_24h()
        assert result is not None
        assert len(result) == 24
        q = storage.query_klines.call_args.args[0]
        assert q.limit == 24

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        storage = MagicMock()
        storage.query_klines = AsyncMock(side_effect=RuntimeError("boom"))
        t = _thread(kline_storage=storage)
        assert await t._collect_klines_24h() is None


class TestCollectMarketData:
    @pytest.mark.asyncio
    async def test_injects_klines_fields(self):
        t = _thread()
        fake_klines = [{"t": 1, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}]
        t._collect_klines_24h = AsyncMock(return_value=fake_klines)
        from vibe_trading.threads import macro_thread as mt

        with (
            patch.object(
                mt.sentiment_tools,
                "get_fear_and_greed_index",
                new=AsyncMock(return_value={"value": 50}),
            ),
            patch.object(
                mt.fundamental_tools,
                "get_funding_rates",
                new=AsyncMock(return_value={"rate": 0.01}),
            ),
            patch.object(
                mt.market_data_tools,
                "get_24hr_ticker",
                new=AsyncMock(return_value={"price": 1.0}),
            ),
            patch.object(
                mt.sentiment_tools,
                "get_trending_symbols",
                new=AsyncMock(return_value=[]),
            ),
        ):
            data = await t._collect_market_data()
        assert data["klines_24h"] == fake_klines
        assert data["klines_24h_interval"] == "30m"
        assert data["klines_24h_hours"] == 24

    @pytest.mark.asyncio
    async def test_not_injects_when_none(self):
        t = _thread()
        t._collect_klines_24h = AsyncMock(return_value=None)
        from vibe_trading.threads import macro_thread as mt

        with (
            patch.object(
                mt.sentiment_tools,
                "get_fear_and_greed_index",
                new=AsyncMock(return_value={"value": 50}),
            ),
            patch.object(
                mt.fundamental_tools,
                "get_funding_rates",
                new=AsyncMock(return_value={"rate": 0.01}),
            ),
            patch.object(
                mt.market_data_tools,
                "get_24hr_ticker",
                new=AsyncMock(return_value={"price": 1.0}),
            ),
            patch.object(
                mt.sentiment_tools,
                "get_trending_symbols",
                new=AsyncMock(return_value=[]),
            ),
        ):
            data = await t._collect_market_data()
        assert "klines_24h" not in data


class TestGetStatistics:
    def test_includes_interval_seconds(self):
        t = _thread()
        t.interval_seconds = 7200
        stats = t.get_statistics()
        assert stats["interval_seconds"] == 7200
        assert stats["symbol"] == "BTCUSDT"
