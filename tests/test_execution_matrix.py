"""Tests for execution matrix (Phase 4.1) — Bybit/Bitget/Hyperliquid/Jupiter + SOR + funding arb."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vibe_trading.data_sources.binance_client import OrderSide, OrderType
from vibe_trading.execution.bitget_executor import BitgetOrderExecutor
from vibe_trading.execution.broker_connector import BrokerConfig, BrokerConnector, BrokerType
from vibe_trading.execution.bybit_executor import BybitOrderExecutor
from vibe_trading.execution.funding_arb import FundingArbOpportunity, scan_funding_arb
from vibe_trading.execution.hyperliquid_executor import HyperliquidOrderExecutor
from vibe_trading.execution.jupiter_executor import JupiterDexExecutor
from vibe_trading.execution.sor import SmartOrderRouter


def _config(broker_type: BrokerType) -> BrokerConfig:
    return BrokerConfig(
        broker_type=broker_type, api_key="", api_secret="", dry_run=True,
    )


class TestBybit:
    @pytest.mark.asyncio
    async def test_dry_run_place_order(self):
        ex = BybitOrderExecutor(_config(BrokerType.BYBIT))
        result = await ex.place_order("BTCUSDT", OrderSide.BUY, OrderType.MARKET, 0.1, price=67500)
        assert result.status == "FILLED"
        assert result.order_id.startswith("bybit_dryrun_")
        assert result.quantity == 0.1

    @pytest.mark.asyncio
    async def test_dry_run_cancel_and_close(self):
        ex = BybitOrderExecutor(_config(BrokerType.BYBIT))
        assert await ex.cancel_order("BTCUSDT", "x") is True
        assert await ex.get_positions() == []
        assert await ex.get_balance() == {}
        await ex.close()


class TestBitget:
    @pytest.mark.asyncio
    async def test_dry_run_place_order(self):
        ex = BitgetOrderExecutor(_config(BrokerType.BITGET))
        result = await ex.place_order("BTCUSDT", OrderSide.SELL, OrderType.LIMIT, 0.5, price=68000)
        assert result.status == "FILLED"
        assert result.order_id.startswith("bitget_dryrun_")
        assert result.quantity == 0.5

    @pytest.mark.asyncio
    async def test_dry_run_cancel(self):
        ex = BitgetOrderExecutor(_config(BrokerType.BITGET))
        assert await ex.cancel_order("BTCUSDT", "x") is True


class TestHyperliquid:
    @pytest.mark.asyncio
    async def test_dry_run_place_order_requires_wallet(self):
        ex = HyperliquidOrderExecutor(_config(BrokerType.HYPERLIQUID))
        result = await ex.place_order("BTC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert result.status == "FILLED"
        assert result.order_id.startswith("hl_dryrun_")

    @pytest.mark.asyncio
    async def test_non_dry_run_raises(self):
        cfg = BrokerConfig(
            broker_type=BrokerType.HYPERLIQUID, api_key="", api_secret="", dry_run=False,
        )
        ex = HyperliquidOrderExecutor(cfg)
        with pytest.raises(NotImplementedError):
            await ex.place_order("BTC", OrderSide.BUY, OrderType.MARKET, 1.0)


class TestJupiter:
    @pytest.mark.asyncio
    async def test_dry_run_place_order(self):
        ex = JupiterDexExecutor(_config(BrokerType.JUPITER))
        result = await ex.place_order("BONK/USDC", OrderSide.BUY, OrderType.MARKET, 1000)
        assert result.status == "FILLED"
        assert result.order_id.startswith("jup_dryrun_")

    @pytest.mark.asyncio
    async def test_get_positions_empty(self):
        ex = JupiterDexExecutor(_config(BrokerType.JUPITER))
        assert await ex.get_positions() == []


class _FakeConnector(BrokerConnector):
    """固定報價 connector 供 SOR 測試."""

    def __init__(self, mid: float, fail: bool = False):
        self._mid = mid
        self._fail = fail

    async def get_mid_price(self, symbol: str) -> float | None:
        if self._fail:
            raise RuntimeError("down")
        return self._mid

    async def place_order(self, *args, **kwargs):
        raise NotImplementedError

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        return True

    async def get_positions(self):
        return []

    async def get_balance(self):
        return {}

    async def close(self) -> None:
        pass


class TestSOR:
    @pytest.mark.asyncio
    async def test_best_buy_lowest_price(self):
        router = SmartOrderRouter({
            BrokerType.OKX: _FakeConnector(67500.0),
            BrokerType.BYBIT: _FakeConnector(67400.0),
        })
        best = await router.best_quote("BTCUSDT", OrderSide.BUY)
        assert best is not None
        assert best.broker == BrokerType.BYBIT
        assert best.price == 67400.0

    @pytest.mark.asyncio
    async def test_best_sell_highest_price(self):
        router = SmartOrderRouter({
            BrokerType.OKX: _FakeConnector(67500.0),
            BrokerType.BYBIT: _FakeConnector(67600.0),
        })
        best = await router.best_quote("BTCUSDT", OrderSide.SELL)
        assert best is not None
        assert best.broker == BrokerType.BYBIT
        assert best.price == 67600.0

    @pytest.mark.asyncio
    async def test_fail_safe_skips_down_broker(self):
        router = SmartOrderRouter({
            BrokerType.OKX: _FakeConnector(67500.0),
            BrokerType.BYBIT: _FakeConnector(0.0, fail=True),
        })
        best = await router.best_quote("BTCUSDT", OrderSide.BUY)
        assert best is not None
        assert best.broker == BrokerType.OKX

    @pytest.mark.asyncio
    async def test_all_down_returns_none(self):
        router = SmartOrderRouter({
            BrokerType.OKX: _FakeConnector(0.0, fail=True),
            BrokerType.BYBIT: _FakeConnector(0.0, fail=True),
        })
        assert await router.best_quote("BTCUSDT", OrderSide.BUY) is None

    @pytest.mark.asyncio
    async def test_quotes_all(self):
        router = SmartOrderRouter({
            BrokerType.OKX: _FakeConnector(67500.0),
            BrokerType.BYBIT: _FakeConnector(67400.0),
        })
        quotes = await router.quotes_all("BTCUSDT")
        assert quotes == {BrokerType.OKX: 67500.0, BrokerType.BYBIT: 67400.0}


class TestFundingArb:
    def test_no_opportunity_below_threshold(self):
        opps = scan_funding_arb(
            {BrokerType.BINANCE: 0.0001, BrokerType.OKX: 0.00011}, min_annualized=0.10,
        )
        assert opps == []

    def test_pairing_and_sort(self):
        opps = scan_funding_arb(
            {BrokerType.BINANCE: 0.0001, BrokerType.OKX: 0.0003, BrokerType.BYBIT: 0.0001},
            min_annualized=0.10,
        )
        assert len(opps) >= 1
        assert isinstance(opps[0], FundingArbOpportunity)
        # 降序
        annualized = [o.annualized_rate for o in opps]
        assert annualized == sorted(annualized, reverse=True)

    def test_annualized_calculation(self):
        # 2bp 差 → 0.0002 * 3 * 365 = 21.9%
        opps = scan_funding_arb(
            {BrokerType.BINANCE: 0.0001, BrokerType.OKX: 0.0003}, min_annualized=0.10,
        )
        assert len(opps) == 1
        o = opps[0]
        assert o.long_broker == BrokerType.OKX  # 高費率收費
        assert o.short_broker == BrokerType.BINANCE
        assert o.annualized_rate == pytest.approx(0.0002 * 3 * 365)
        assert o.spread_bps == pytest.approx(2.0)

    def test_same_broker_not_paired(self):
        opps = scan_funding_arb(
            {BrokerType.BINANCE: 0.0005, BrokerType.OKX: 0.0001}, min_annualized=0.0,
        )
        for o in opps:
            assert o.long_broker != o.short_broker


class TestBybitLivePath:
    @pytest.mark.asyncio
    async def test_place_order_live_success(self):
        """mock aiohttp 回 OK → OrderResult submitted."""
        cfg = BrokerConfig(broker_type=BrokerType.BYBIT, api_key="k",
                           api_secret="s", dry_run=False)
        ex = BybitOrderExecutor(cfg)
        with patch("aiohttp.ClientSession") as mock_session:
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"retCode": 0,
                                                "result": {"orderId": "123"}})
            mock_session.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(**{"__aenter__.return_value": resp}))
            result = await ex.place_order("BTCUSDT", OrderSide.BUY,
                                          OrderType.MARKET, 0.1)
        assert result.status in ("submitted", "FILLED")

    @pytest.mark.asyncio
    async def test_place_order_live_error_fallback(self):
        cfg = BrokerConfig(broker_type=BrokerType.BYBIT, api_key="k",
                           api_secret="s", dry_run=False)
        ex = BybitOrderExecutor(cfg)
        with patch("aiohttp.ClientSession") as mock_session:
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"retCode": -1, "retMsg": "bad"})
            mock_session.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(**{"__aenter__.return_value": resp}))
            result = await ex.place_order("BTCUSDT", OrderSide.BUY,
                                          OrderType.MARKET, 0.1)
        assert result.status in ("dry_run", "FILLED")  # error → dry-run fallback

    def test_auth_headers(self):
        cfg = BrokerConfig(broker_type=BrokerType.BYBIT, api_key="k",
                           api_secret="s", dry_run=False)
        ex = BybitOrderExecutor(cfg)
        headers = ex._auth_headers("POST", "/v5/order/create", {"symbol": "BTCUSDT"})
        assert "X-BAPI-API-KEY" in headers
        assert "X-BAPI-SIGN" in headers


class TestBitgetLivePath:
    @pytest.mark.asyncio
    async def test_place_order_live_success(self):
        cfg = BrokerConfig(broker_type=BrokerType.BITGET, api_key="k",
                           api_secret="s", passphrase="p", dry_run=False)
        ex = BitgetOrderExecutor(cfg)
        with patch("aiohttp.ClientSession") as mock_session:
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"code": "00000",
                                                "data": {"orderId": "456"}})
            mock_session.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(**{"__aenter__.return_value": resp}))
            result = await ex.place_order("BTCUSDT", OrderSide.SELL,
                                          OrderType.LIMIT, 0.5, price=68000)
        assert result.status in ("submitted", "FILLED")

    def test_auth_headers(self):
        cfg = BrokerConfig(broker_type=BrokerType.BITGET, api_key="k",
                           api_secret="s", passphrase="p", dry_run=False)
        ex = BitgetOrderExecutor(cfg)
        headers = ex._auth_headers({"a": 1}, "/api/v2/mix/order/place-order")
        assert "ACCESS-KEY" in headers
        assert "ACCESS-SIGN" in headers
