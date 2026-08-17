"""L1: Derivatives Provider 測試 (規格書 §2.3)."""
from unittest.mock import AsyncMock, patch

import pytest

from vibe_trading.data_sources.providers.derivatives_provider import (
    DerivativesDataProvider,
)


@pytest.fixture
def provider():
    return DerivativesDataProvider()


class TestDerivativesMetrics:
    @pytest.mark.asyncio
    async def test_metrics_full(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"funding_rate": 0.0001})), \
             patch("vibe_trading.tools.fundamental_tools.get_open_interest",
                   new=AsyncMock(return_value={"open_interest": 1.25e9})), \
             patch("vibe_trading.tools.fundamental_tools.get_taker_buy_sell_ratio",
                   new=AsyncMock(return_value={"buy_sell_ratio": 1.15})):
            r = await provider.get_derivatives_metrics("BTCUSDT")
        assert r["funding_rate"] == 0.0001
        assert r["funding_rate_annualized"] == pytest.approx(10.95)
        assert r["open_interest_usd"] == 1.25e9
        assert r["taker_buy_sell_ratio"] == 1.15
        assert r["squeeze_risk"] == "NEUTRAL"

    @pytest.mark.asyncio
    async def test_long_squeeze(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"funding_rate": 0.0006})):
            r = await provider.get_derivatives_metrics("BTCUSDT")
        assert r["squeeze_risk"] == "LONG_SQUEEZE_RISK"

    @pytest.mark.asyncio
    async def test_short_squeeze(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"funding_rate": -0.0004})):
            r = await provider.get_derivatives_metrics("BTCUSDT")
        assert r["squeeze_risk"] == "SHORT_SQUEEZE_RISK"

    @pytest.mark.asyncio
    async def test_api_failure_degraded(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("vibe_trading.tools.fundamental_tools.get_open_interest",
                   new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("vibe_trading.tools.fundamental_tools.get_taker_buy_sell_ratio",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            r = await provider.get_derivatives_metrics("BTCUSDT")
        assert r["funding_rate"] is None
        assert "funding" in r["degraded"]
        assert r["squeeze_risk"] == "NEUTRAL"


class TestDerivativeMethods:
    @pytest.mark.asyncio
    async def test_funding_zscore(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"funding_rate": 0.0002})):
            z = await provider.get_funding_rate_zscore("BTCUSDT")
        assert z is not None and z > 0

    @pytest.mark.asyncio
    async def test_funding_zscore_error(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            assert await provider.get_funding_rate_zscore("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_funding_zscore_missing_key(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_funding_rates",
                   new=AsyncMock(return_value={"error": "no data"})):
            assert await provider.get_funding_rate_zscore("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_oi_surge(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_open_interest",
                   new=AsyncMock(return_value={"open_interest": 1.0e9})):
            s = await provider.get_oi_surge_ratio("BTCUSDT")
        assert s is not None

    @pytest.mark.asyncio
    async def test_taker_ratio(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_taker_buy_sell_ratio",
                   new=AsyncMock(return_value={"buy_sell_ratio": 1.2})):
            t = await provider.get_taker_volume_ratio("BTCUSDT")
        assert t == 1.2

    @pytest.mark.asyncio
    async def test_taker_ratio_missing(self, provider):
        with patch("vibe_trading.tools.fundamental_tools.get_taker_buy_sell_ratio",
                   new=AsyncMock(return_value={"error": "x"})):
            assert await provider.get_taker_volume_ratio("BTCUSDT") is None
