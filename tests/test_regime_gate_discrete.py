import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.rule_engine.regime_gate import (
    DISCRETE_QTY,
    DISCRETE_THR,
    Regime,
    current_regime,
    current_regime_with_score,
)


def _state(regime="RISK_ON", strength="STRONG", detail="CHOPPY", ts=None):
    s = MagicMock()
    s.market_regime = regime
    s.trend_strength = strength
    s.regime_detail = detail
    s.timestamp = ts or int(time.time() * 1000)
    return s


class TestDiscreteConstants:
    def test_qty_map(self):
        assert DISCRETE_QTY == {"CHOPPY": 0.3, "TRENDING": 1.0, "UNCERTAIN": 0.5}

    def test_thr_map(self):
        assert DISCRETE_THR == {"CHOPPY": 1.4, "TRENDING": 1.0, "UNCERTAIN": 1.2}


class TestCurrentRegimeWithScore:
    @pytest.mark.asyncio
    async def test_choppy_detail(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="CHOPPY"))
        regime, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "CHOPPY"

    @pytest.mark.asyncio
    async def test_trending_detail(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="TRENDING"))
        _, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "TRENDING"

    @pytest.mark.asyncio
    async def test_uncertain_detail(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="UNCERTAIN"))
        _, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_stale_returns_neutral_uncertain(self):
        stale = int(time.time() * 1000) - 20000 * 1000
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="CHOPPY", ts=stale))
        regime, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert regime == Regime.NEUTRAL
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_no_state_returns_neutral_uncertain(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=None)
        regime, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert regime == Regime.NEUTRAL
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_read_error_returns_neutral_uncertain(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(side_effect=RuntimeError("db down"))
        regime, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert regime == Regime.NEUTRAL
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_missing_detail_attr_fallback_uncertain(self):
        s = MagicMock(spec=[])
        s.market_regime = "NEUTRAL"
        s.trend_strength = "MODERATE"
        s.timestamp = int(time.time() * 1000)
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=s)
        _, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_unknown_detail_fallback_uncertain(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="FLUFFY"))
        _, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_case_insensitive_detail(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="choppy"))
        _, detail = await current_regime_with_score(storage, max_age_seconds=14400)
        assert detail == "CHOPPY"

    @pytest.mark.asyncio
    async def test_wrapper_current_regime_still_works(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(regime="BULL", detail="TRENDING"))
        r = await current_regime(storage)
        assert r == Regime.RISK_ON

    @pytest.mark.asyncio
    async def test_default_max_age_14400(self):
        borderline = int(time.time() * 1000) - 14400 * 1000 + 5000
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=_state(detail="TRENDING", ts=borderline))
        _, detail = await current_regime_with_score(storage)
        assert detail == "TRENDING"
