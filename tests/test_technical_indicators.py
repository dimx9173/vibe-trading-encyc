"""Tests for TechnicalAnalyzer indicators (Wave A — coverage 85% plan)."""
from datetime import datetime, timezone

import pytest

from vibe_trading.data_sources.base import Kline
from vibe_trading.data_sources.indicators.technical import TechnicalAnalyzer


def _kline(i: int, close: float, high: float | None = None, low: float | None = None,
           volume: float = 100.0) -> Kline:
    return Kline(
        symbol="BTCUSDT", interval="1h",
        open_time=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(hour=i % 24),
        open=close * 0.999, high=high or close * 1.01, low=low or close * 0.99,
        close=close, volume=volume,
    )


def _klines(n: int, base: float = 100.0, step: float = 1.0) -> list[Kline]:
    return [_kline(i, base + step * i) for i in range(n)]


class TestCalculate:
    def test_less_than_30_empty(self):
        assert TechnicalAnalyzer.calculate(_klines(10)) == {}

    def test_30_plus_all_indicators(self):
        ind = TechnicalAnalyzer.calculate(_klines(60))
        expected = {"rsi_14", "macd", "macd_signal", "bollinger_upper", "bollinger_middle",
                    "bollinger_lower", "sma_20", "sma_50", "ema_12", "ema_26", "atr_14",
                    "volume_sma_20"}
        assert set(ind.keys()) == expected

    def test_constant_series(self):
        ind = TechnicalAnalyzer.calculate(_klines(60, step=0.0))
        # 常數: RSI=100, bollinger middle=100, 上下=100
        assert ind["rsi_14"] == 100.0
        assert ind["bollinger_middle"] == pytest.approx(100.0)
        assert ind["bollinger_upper"] == pytest.approx(100.0)
        assert ind["sma_20"] == pytest.approx(100.0)


class TestSMA:
    def test_sma_basic(self):
        assert TechnicalAnalyzer._calculate_sma([1.0, 2.0, 3.0, 4.0], 3) == pytest.approx(3.0)

    def test_sma_short(self):
        assert TechnicalAnalyzer._calculate_sma([1.0, 2.0], 3) == 0.0


class TestEMA:
    def test_ema_basic(self):
        data = [1.0] * 10 + [2.0] * 10
        ema = TechnicalAnalyzer._calculate_ema(data, 5)
        assert ema > 1.0  # 後半上升 → EMA > 初始均值
        assert ema <= 2.0

    def test_ema_short(self):
        assert TechnicalAnalyzer._calculate_ema([1.0, 2.0], 5) == 0.0

    def test_ema_constant(self):
        assert TechnicalAnalyzer._calculate_ema([5.0] * 20, 5) == pytest.approx(5.0)


class TestRSI:
    def test_rsi_short(self):
        assert TechnicalAnalyzer._calculate_rsi([1.0, 2.0]) == 50.0

    def test_rsi_all_up(self):
        closes = [100.0 + i for i in range(20)]
        assert TechnicalAnalyzer._calculate_rsi(closes) == 100.0

    def test_rsi_all_down(self):
        closes = [100.0 - i for i in range(20)]
        assert TechnicalAnalyzer._calculate_rsi(closes) == 0.0

    def test_rsi_mixed(self):
        closes = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.5, 104.0,
                  103.5, 105.0, 104.5, 106.0, 105.5, 107.0, 106.5, 108.0]
        rsi = TechnicalAnalyzer._calculate_rsi(closes)
        assert 50.0 < rsi < 100.0  # 漲多跌少


class TestMACD:
    def test_macd_short(self):
        assert TechnicalAnalyzer._calculate_macd([1.0] * 10) == 0.0

    def test_macd_up_trend(self):
        closes = [100.0 + i for i in range(40)]
        macd = TechnicalAnalyzer._calculate_macd(closes)
        assert macd > 0.0  # 上升趨勢 → EMA12 > EMA26

    def test_macd_signal_short(self):
        assert TechnicalAnalyzer._calculate_macd_signal([1.0] * 10) == 0.0

    def test_macd_signal_up_trend(self):
        closes = [100.0 + i for i in range(50)]
        signal = TechnicalAnalyzer._calculate_macd_signal(closes)
        assert signal > 0.0


class TestBollinger:
    def test_upper_lower_short(self):
        assert TechnicalAnalyzer._calculate_bollinger_upper([1.0] * 10) == 0.0
        assert TechnicalAnalyzer._calculate_bollinger_lower([1.0] * 10) == 0.0

    def test_bands_symmetric(self):
        closes = [100.0 + i for i in range(25)]
        middle = TechnicalAnalyzer._calculate_bollinger_middle(closes)
        upper = TechnicalAnalyzer._calculate_bollinger_upper(closes)
        lower = TechnicalAnalyzer._calculate_bollinger_lower(closes)
        assert upper > middle > lower
        assert (upper - middle) == pytest.approx(middle - lower)

    def test_middle_is_sma(self):
        closes = [100.0 + i for i in range(25)]
        assert TechnicalAnalyzer._calculate_bollinger_middle(closes) == \
            pytest.approx(TechnicalAnalyzer._calculate_sma(closes, 20))


class TestATR:
    def test_atr_short(self):
        assert TechnicalAnalyzer._calculate_atr([1.0], [1.0], [1.0]) == 0.0

    def test_atr_basic(self):
        highs = [110.0 + i for i in range(20)]
        lows = [90.0 + i for i in range(20)]
        closes = [100.0 + i for i in range(20)]
        atr = TechnicalAnalyzer._calculate_atr(highs, lows, closes)
        assert atr > 0.0
        # TR = high - low = 20 (dominant), 平均 ≈ 20
        assert atr == pytest.approx(20.0, abs=0.01)

    def test_atr_flat(self):
        highs = [100.0] * 20
        lows = [100.0] * 20
        closes = [100.0] * 20
        assert TechnicalAnalyzer._calculate_atr(highs, lows, closes) == 0.0
