"""Tests for TechnicalIndicators class (Wave D — coverage 85% plan)."""
import pytest

from vibe_trading.data_sources.technical_indicators import (
    Indicators,
    TechnicalIndicators,
)


def _series(n: int = 100, base: float = 100.0, step: float = 1.0):
    opens = [base + step * i for i in range(n)]
    highs = [o * 1.01 for o in opens]
    lows = [o * 0.99 for o in opens]
    closes = [base + step * i for i in range(n)]
    volumes = [1000.0] * n
    return opens, highs, lows, closes, volumes


class TestGetRequiredLookback:
    def test_all_indicators(self):
        # macd 35, stochastic 14, sma_50 50 → 50 * 1.2 = 60
        assert TechnicalIndicators.get_required_lookback() == 60

    def test_macd_only(self):
        assert TechnicalIndicators.get_required_lookback(["macd"]) == 42

    def test_stochastic_only(self):
        assert TechnicalIndicators.get_required_lookback(["stochastic"]) == 16

    def test_unknown_indicator_zero(self):
        assert TechnicalIndicators.get_required_lookback(["nope"]) == 0

    def test_sma_period(self):
        assert TechnicalIndicators.get_required_lookback(["sma_50"]) == 60

    def test_safety_margin(self):
        assert TechnicalIndicators.get_required_lookback(["rsi"], safety_margin=0.0) == 14


class TestLoadData:
    def test_load(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series()
        ti.load_data(o, h, l, c, v)
        assert ti.data is not None
        assert len(ti.data) == 100
        assert "close" in ti.data.columns

    def test_load_with_timestamps(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(60)
        ti.load_data(o, h, l, c, v, timestamps=[i for i in range(60)])
        assert "timestamp" in ti.data.columns


class TestCalculateAll:
    def test_insufficient_data(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(10)
        ti.load_data(o, h, l, c, v)
        with pytest.raises(ValueError):
            ti.calculate_all()

    def test_calculate_all_columns(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        df = ti.calculate_all()
        for col in ("sma_20", "sma_50", "ema_12", "ema_26", "rsi", "macd",
                    "macd_signal", "macd_hist", "bb_upper", "bb_middle",
                    "bb_lower", "atr", "volume_sma", "stoch_k", "stoch_d", "obv"):
            assert col in df.columns

    def test_get_latest_indicators(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        ind = ti.get_latest_indicators()
        assert isinstance(ind, Indicators)
        assert ind.sma_20 is not None


class TestTrendAnalysis:
    def test_get_trend_analysis(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        analysis = ti.get_trend_analysis()
        assert isinstance(analysis, dict)
        assert len(analysis) > 0


class TestPatterns:
    def test_detect_candlestick_patterns(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        patterns = ti.detect_candlestick_patterns(lookback=10)
        assert isinstance(patterns, dict)

    def test_summarize_patterns(self):
        ti = TechnicalIndicators()
        summary = ti._summarize_patterns({
            "reversal": [{"signal": "bullish_engulfing"}, {"signal": "bearish_engulfing"}],
            "continuation": [{"signal": "bullish_flag"}],
            "single": [{"type": "doji"}],
        })
        assert isinstance(summary, str)

    def test_summarize_patterns_empty(self):
        ti = TechnicalIndicators()
        assert "未检测到" in ti._summarize_patterns(
            {"reversal": [], "continuation": [], "single": []})


class TestVolume:
    def test_analyze_volume(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        result = ti.analyze_volume(lookback=10)
        assert isinstance(result, dict)


class TestDivergence:
    def test_insufficient_data(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(20)
        ti.load_data(o, h, l, c, v)
        result = ti.detect_divergence()
        assert result["found"] is False

    def test_no_data(self):
        ti = TechnicalIndicators()
        result = ti.detect_divergence()
        assert result["found"] is False

    def test_detect_with_data(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        result = ti.detect_divergence(lookback=30)
        assert "divergences" in result

    def test_unknown_indicator(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        result = ti.detect_divergence(indicator="bogus")
        assert "error" in result

    def test_summarize_divergences(self):
        ti = TechnicalIndicators()
        s = ti._summarize_divergences(
            {"bullish": [{"strength": "strong"}], "bearish": []}, "rsi")
        assert "看涨背离" in s

    def test_summarize_none(self):
        ti = TechnicalIndicators()
        s = ti._summarize_divergences({"bullish": [], "bearish": []}, "macd")
        assert "未检测到" in s


class TestVolume:
    def test_volume_insufficient(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(10)
        ti.load_data(o, h, l, c, v)
        result = ti.analyze_volume(lookback=20)
        assert "error" in result


class TestMultiTimeframe:
    def test_multi_timeframe(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(150)
        result = ti.multi_timeframe_analysis(o, h, l, c, v)
        assert isinstance(result, dict)


class TestCandlestickEmpty:
    def test_no_data(self):
        ti = TechnicalIndicators()
        assert "error" in ti.detect_candlestick_patterns()

    def test_insufficient_data(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(10)
        ti.load_data(o, h, l, c, v)
        assert "error" in ti.detect_candlestick_patterns(lookback=20)

    def test_patterns_full(self):
        ti = TechnicalIndicators()
        o, h, l, c, v = _series(100)
        ti.load_data(o, h, l, c, v)
        result = ti.detect_candlestick_patterns(lookback=50)
        assert isinstance(result, dict)
        assert "single" in result["patterns"]
        assert "reversal" in result["patterns"]
        assert "continuation" in result["patterns"]
