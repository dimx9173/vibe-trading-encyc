"""Tests for rule_engine/regime_gate.py (spec phase1 §7: mapping table + fail-safe)."""
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.rule_engine.regime_gate import (
    Regime,
    current_regime,
    map_macro_to_regime,
)


class TestMapMacroToRegime:
    def test_bull_is_risk_on(self):
        assert map_macro_to_regime("BULL", 0.3) == Regime.RISK_ON

    def test_bull_weak_trend_still_risk_on(self):
        assert map_macro_to_regime("BULL", 0.0) == Regime.RISK_ON

    def test_bear_strong_trend_risk_off(self):
        assert map_macro_to_regime("BEAR", 0.7) == Regime.RISK_OFF

    def test_bear_strong_string_trend_risk_off(self):
        assert map_macro_to_regime("BEAR", "STRONG") == Regime.RISK_OFF

    def test_bear_weak_trend_neutral(self):
        assert map_macro_to_regime("BEAR", 0.4) == Regime.NEUTRAL

    def test_bear_weak_string_neutral(self):
        assert map_macro_to_regime("BEAR", "WEAK") == Regime.NEUTRAL

    def test_bear_moderate_string_neutral(self):
        assert map_macro_to_regime("BEAR", "MODERATE") == Regime.NEUTRAL

    def test_old_neutral_is_neutral(self):
        assert map_macro_to_regime("NEUTRAL", 0.9) == Regime.NEUTRAL

    def test_new_three_state_passthrough(self):
        assert map_macro_to_regime("RISK_ON", 0.1) == Regime.RISK_ON
        assert map_macro_to_regime("RISK_OFF", 0.9) == Regime.RISK_OFF
        assert map_macro_to_regime("RISK_OFF", 0.1) == Regime.RISK_OFF
        assert map_macro_to_regime("NEUTRAL", 0.9) == Regime.NEUTRAL

    def test_case_insensitive(self):
        assert map_macro_to_regime("bull", 0.5) == Regime.RISK_ON
        assert map_macro_to_regime("bear", "strong") == Regime.RISK_OFF

    def test_unknown_regime_failsafe_neutral(self):
        assert map_macro_to_regime("FOO", 1.0) == Regime.NEUTRAL

    def test_empty_regime_failsafe_neutral(self):
        assert map_macro_to_regime("", 1.0) == Regime.NEUTRAL
        assert map_macro_to_regime(None, 1.0) == Regime.NEUTRAL

    def test_numeric_trend_strength_used_directly(self):
        assert map_macro_to_regime("BEAR", 0.6) == Regime.RISK_OFF
        assert map_macro_to_regime("BEAR", 0.59) == Regime.NEUTRAL


class TestCurrentRegime:
    def _state(self, regime: str = "BULL", strength: str = "STRONG",
               timestamp_ms: "Optional[int]" = None) -> MagicMock:
        state = MagicMock()
        state.market_regime = regime
        state.trend_strength = strength
        state.overall_sentiment = "POSITIVE"
        state.timestamp = timestamp_ms or int(time.time() * 1000)
        return state

    @pytest.mark.asyncio
    async def test_no_state_failsafe_neutral(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=None)
        assert await current_regime(storage) == Regime.NEUTRAL

    @pytest.mark.asyncio
    async def test_stale_state_failsafe_neutral(self):
        stale = int(time.time() * 1000) - 3 * 3600 * 1000
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=self._state(timestamp_ms=stale))
        assert await current_regime(storage) == Regime.NEUTRAL

    @pytest.mark.asyncio
    async def test_fresh_bull_risk_on(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=self._state("BULL", "STRONG"))
        assert await current_regime(storage) == Regime.RISK_ON

    @pytest.mark.asyncio
    async def test_fresh_new_three_state_risk_off(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=self._state("RISK_OFF", "WEAK"))
        assert await current_regime(storage) == Regime.RISK_OFF

    @pytest.mark.asyncio
    async def test_read_error_failsafe_neutral(self):
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(side_effect=RuntimeError("db down"))
        assert await current_regime(storage) == Regime.NEUTRAL

    @pytest.mark.asyncio
    async def test_reads_latest_state_market_wide(self):
        """macro regime 是市场级判断 — 读取不分 symbol (P0-3)."""
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=None)
        await current_regime(storage, symbol="SOLUSDT")
        storage.get_latest_state.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_eth_loop_reads_btc_written_regime(self):
        """macro 线程只写主 symbol (BTCUSDT)，ETH 的 loop 读到相同 regime (P0-3)."""
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=self._state("BULL", "STRONG"))
        assert await current_regime(storage, symbol="ETHUSDT") == Regime.RISK_ON
        storage.get_latest_state.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_future_timestamp_not_stale(self):
        future = int(time.time() * 1000) + 60_000
        storage = MagicMock()
        storage.get_latest_state = AsyncMock(return_value=self._state("NEUTRAL", "MODERATE", future))
        assert await current_regime(storage) == Regime.NEUTRAL