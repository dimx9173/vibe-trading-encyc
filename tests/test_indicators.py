"""
Test for technical_indicators.py

Pure-math indicator calculations + TechnicalIndicators class.
No mocks needed — these are isolated functions over pandas Series.
"""
import numpy as np
import pandas as pd
import pytest

from vibe_trading.data_sources.technical_indicators import (
    Indicators,
    TechnicalIndicators,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_obv,
    calculate_rsi,
    calculate_sma,
    calculate_stochastic,
)


# === Pure function tests ===

class TestSMA:
    def test_sma_constant_series(self):
        s = pd.Series([10.0] * 30)
        out = calculate_sma(s, 5)
        result = out.dropna().iloc[-1]
        assert result == 10.0

    def test_sma_known_value(self):
        # Linear series 1..10, period=3 → window [8,9,10] mean = 9
        s = pd.Series(range(1, 11), dtype=float)
        out = calculate_sma(s, 3)
        assert out.iloc[-1] == 9.0

    def test_sma_nan_before_period(self):
        s = pd.Series(range(1, 11), dtype=float)
        out = calculate_sma(s, 5)
        # First 4 entries must be NaN
        assert out.iloc[:4].isna().all()
        assert not out.isna().iloc[-1]


class TestEMA:
    def test_ema_constant_series(self):
        s = pd.Series([50.0] * 30)
        out = calculate_ema(s, 10)
        # EMA of a constant is the constant
        assert np.isclose(out.dropna().iloc[-1], 50.0)

    def test_ema_reacts_faster_than_sma_to_jump(self):
        # Sudden jump at end: constant 10 for 50 bars, then 20
        s = pd.Series([10.0] * 50 + [20.0], dtype=float)
        ema = calculate_ema(s, 10).iloc[-1]
        sma = calculate_sma(s, 10).iloc[-1]
        # EMA should be closer to the new value than SMA
        assert ema > sma

    def test_ema_returns_series(self):
        s = pd.Series(range(1, 21), dtype=float)
        out = calculate_ema(s, 5)
        assert isinstance(out, pd.Series)
        assert len(out) == len(s)


class TestRSI:
    def test_rsi_pure_uptrend_is_100(self):
        # Strictly increasing → all gains, no losses → RSI = 100
        s = pd.Series(range(1, 30), dtype=float)
        rsi = calculate_rsi(s, 14)
        assert np.isclose(rsi.iloc[-1], 100.0)

    def test_rsi_pure_downtrend_is_0(self):
        s = pd.Series(range(30, 0, -1), dtype=float)
        rsi = calculate_rsi(s, 14)
        assert np.isclose(rsi.iloc[-1], 0.0)

    def test_rsi_flat_is_50_or_undefined(self):
        # Flat series: gain=0, loss=0 → division by zero → could be NaN
        # We just assert it doesn't crash and yields a sensible value
        s = pd.Series([100.0] * 30)
        rsi = calculate_rsi(s, 14)
        # Either NaN (from 0/0) or 50; we accept both but require finite or NaN
        val = rsi.iloc[-1]
        assert np.isnan(val) or (40 <= val <= 60)

    def test_rsi_default_period_14(self):
        s = pd.Series(range(1, 30), dtype=float)
        rsi = calculate_rsi(s)
        assert len(rsi) == len(s)
        # First 13 are NaN: delta[0]=NaN propagates through rolling(14) until
        # 14 valid values are available (positions 14+).
        assert rsi.iloc[:13].isna().all()
        assert not rsi.isna().iloc[-1]


class TestMACD:
    def test_macd_returns_three_series(self):
        s = pd.Series(range(1, 100), dtype=float)
        macd, signal, hist = calculate_macd(s)
        assert isinstance(macd, pd.Series)
        assert isinstance(signal, pd.Series)
        assert isinstance(hist, pd.Series)
        assert len(macd) == len(s)

    def test_macd_histogram_is_macd_minus_signal(self):
        s = pd.Series(np.random.RandomState(42).normal(100, 5, 100))
        macd, signal, hist = calculate_macd(s)
        # Skip NaN region
        valid = ~(macd.isna() | signal.isna() | hist.isna())
        np.testing.assert_allclose(
            hist[valid].values, (macd[valid] - signal[valid]).values
        )

    def test_macd_uptrend_bullish(self):
        # Steadily rising → MACD line above zero
        s = pd.Series(range(1, 100), dtype=float)
        macd, signal, hist = calculate_macd(s)
        # After warmup, MACD should be positive
        assert macd.iloc[-1] > 0


class TestBollinger:
    def test_bollinger_middle_is_sma(self):
        s = pd.Series(range(1, 50), dtype=float)
        upper, middle, lower = calculate_bollinger_bands(s, period=10)
        sma = calculate_sma(s, 10)
        np.testing.assert_allclose(middle.dropna().values, sma.dropna().values)

    def test_bollinger_upper_above_lower(self):
        s = pd.Series(np.random.RandomState(42).normal(100, 5, 50))
        upper, middle, lower = calculate_bollinger_bands(s)
        # Drop NaN
        valid = ~(upper.isna() | lower.isna())
        assert (upper[valid] > lower[valid]).all()

    def test_bollinger_constant_series_collapses(self):
        # Constant series → std = 0 → upper = middle = lower
        s = pd.Series([100.0] * 30)
        upper, middle, lower = calculate_bollinger_bands(s, period=10)
        valid = ~upper.isna()
        np.testing.assert_allclose(upper[valid].values, middle[valid].values)
        np.testing.assert_allclose(lower[valid].values, middle[valid].values)


class TestATR:
    def test_atr_constant_range(self):
        # Bar with H=L+1, L=C always → true range = 1
        n = 30
        high = pd.Series([101.0] * n)
        low = pd.Series([100.0] * n)
        close = pd.Series([100.0] * n)
        atr = calculate_atr(high, low, close, period=14)
        # After warmup, all TR = 1, so ATR = 1
        assert np.isclose(atr.iloc[-1], 1.0)

    def test_atr_positive(self):
        # Random walk
        rng = np.random.RandomState(42)
        closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, 50)))
        highs = closes + 1
        lows = closes - 1
        atr = calculate_atr(highs, lows, closes, period=14)
        valid = atr.dropna()
        assert (valid > 0).all()


class TestStochastic:
    def test_stochastic_returns_k_d(self):
        rng = np.random.RandomState(42)
        closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, 50)))
        highs = closes + 1
        lows = closes - 1
        k, d = calculate_stochastic(highs, lows, closes)
        assert isinstance(k, pd.Series)
        assert isinstance(d, pd.Series)
        assert len(k) == len(closes)

    def test_stochastic_in_range(self):
        rng = np.random.RandomState(42)
        closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, 50)))
        highs = closes + 1
        lows = closes - 1
        k, d = calculate_stochastic(highs, lows, closes)
        valid_k = k.dropna()
        # K is bounded 0..100 by construction
        assert (valid_k >= 0).all() and (valid_k <= 100).all()


class TestOBV:
    def test_obv_strict_uptrend(self):
        closes = pd.Series([1, 2, 3, 4, 5], dtype=float)
        volumes = pd.Series([10, 10, 10, 10, 10], dtype=float)
        obv = calculate_obv(closes, volumes)
        # All up → cumulative volume
        assert obv.iloc[-1] == 50.0

    def test_obv_strict_downtrend_subtracts(self):
        closes = pd.Series([5, 4, 3, 2, 1], dtype=float)
        volumes = pd.Series([10, 10, 10, 10, 10], dtype=float)
        obv = calculate_obv(closes, volumes)
        # OBV starts at volume[0]=10, then 4 down moves each subtract 10
        # 10 - 4*10 = -30
        assert obv.iloc[-1] == -30.0

    def test_obv_flat_unchanged(self):
        closes = pd.Series([100.0] * 5)
        volumes = pd.Series([10, 20, 30, 40, 50], dtype=float)
        obv = calculate_obv(closes, volumes)
        # All flat → only first volume loaded
        assert obv.iloc[-1] == 10.0


# === TechnicalIndicators class tests ===

class TestTechnicalIndicatorsClass:
    def _make_data(self, n=60, seed=42):
        """Build a deterministic OHLCV dataset with n bars."""
        rng = np.random.RandomState(seed)
        closes = 100 + np.cumsum(rng.normal(0, 1, n))
        highs = closes + np.abs(rng.normal(0, 0.5, n))
        lows = closes - np.abs(rng.normal(0, 0.5, n))
        opens = closes + rng.normal(0, 0.3, n)
        volumes = np.abs(rng.normal(1000, 200, n))
        return (
            opens.tolist(),
            highs.tolist(),
            lows.tolist(),
            closes.tolist(),
            volumes.tolist(),
        )

    def test_calculate_all_requires_min_50_rows(self):
        ti = TechnicalIndicators()
        opens, highs, lows, closes, volumes = self._make_data(n=30)
        ti.load_data(opens, highs, lows, closes, volumes)
        with pytest.raises(ValueError, match="Insufficient data"):
            ti.calculate_all()

    def test_calculate_all_produces_all_columns(self):
        ti = TechnicalIndicators()
        opens, highs, lows, closes, volumes = self._make_data(n=60)
        ti.load_data(opens, highs, lows, closes, volumes)
        df = ti.calculate_all()
        expected = {
            "sma_20", "sma_50", "ema_12", "ema_26",
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_middle", "bb_lower",
            "atr", "volume_sma", "stoch_k", "stoch_d", "obv",
        }
        assert expected.issubset(set(df.columns))

    def test_get_latest_indicators_returns_dataclass(self):
        ti = TechnicalIndicators()
        opens, highs, lows, closes, volumes = self._make_data(n=60)
        ti.load_data(opens, highs, lows, closes, volumes)
        ind = ti.get_latest_indicators()
        assert isinstance(ind, Indicators)
        # rsi and atr should be populated on a real dataset
        assert ind.rsi is not None
        assert ind.atr is not None
        assert 0 <= ind.rsi <= 100

    def test_get_trend_analysis_structure(self):
        ti = TechnicalIndicators()
        opens, highs, lows, closes, volumes = self._make_data(n=60)
        ti.load_data(opens, highs, lows, closes, volumes)
        analysis = ti.get_trend_analysis()
        assert "trend" in analysis
        assert "strength" in analysis
        assert "signals" in analysis
        assert isinstance(analysis["signals"], list)
        assert analysis["trend"] in {"neutral", "up", "down", "strong_up", "strong_down"}

    def test_detect_candlestick_patterns_no_data(self):
        ti = TechnicalIndicators()
        result = ti.detect_candlestick_patterns()
        assert "error" in result

    def test_detect_candlestick_patterns_with_data(self):
        ti = TechnicalIndicators()
        opens, highs, lows, closes, volumes = self._make_data(n=60)
        ti.load_data(opens, highs, lows, closes, volumes)
        result = ti.detect_candlestick_patterns(lookback=20)
        # Should not crash; should return either an error or {"found": True, "patterns": {...}}
        assert "found" in result or "error" in result
        if result.get("found"):
            assert "patterns" in result
            for cat in ("reversal", "continuation", "single"):
                assert cat in result["patterns"]
                assert isinstance(result["patterns"][cat], list)


class TestGetRequiredLookback:
    def test_default_is_all_indicators(self):
        n = TechnicalIndicators.get_required_lookback()
        # Should be the max of all defaults with 20% safety margin
        # max base = 50 (sma_50), * 1.2 = 60
        assert n == 60

    def test_specific_indicator_uses_min_lookback(self):
        # Just RSI: base = 14, * 1.2 = 16.8 → 16
        n = TechnicalIndicators.get_required_lookback(["rsi"])
        assert n == 16

    def test_macd_is_max_fast_slow_plus_signal(self):
        # MACD: max(12, 26) + 9 = 35, * 1.2 = 42
        n = TechnicalIndicators.get_required_lookback(["macd"])
        assert n == 42

    def test_lookback_takes_max_across_indicators(self):
        # sma_50 (50) + macd (35) → 50 * 1.2 = 60
        n = TechnicalIndicators.get_required_lookback(["macd", "sma_50"])
        assert n == 60

    def test_safety_margin_zero(self):
        n = TechnicalIndicators.get_required_lookback(["rsi"], safety_margin=0.0)
        assert n == 14
