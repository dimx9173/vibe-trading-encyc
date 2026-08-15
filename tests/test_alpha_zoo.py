"""Tests for AlphaZoo factors (Wave A — coverage 85% plan)."""
from datetime import datetime, timezone

import pytest

from vibe_trading.data_sources.alphas.zoo import AlphaZoo
from vibe_trading.data_sources.base import Kline


def _mkline(i: int, close: float, high: float | None = None, low: float | None = None,
            volume: float = 100.0) -> Kline:
    """構造單根 kline (open=close 前值近似, high/low 可覆寫)."""
    return Kline(
        symbol="BTCUSDT", interval="1h",
        open_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + __import__("datetime").timedelta(hours=i),
        open=close * 0.999, high=high or close * 1.01, low=low or close * 0.99,
        close=close, volume=volume,
    )


def _klines(n: int, base: float = 100.0, step: float = 1.0, volume: float = 100.0) -> list[Kline]:
    """n 根逐步上升的 kline 序列."""
    return [_mkline(i, base + step * i, volume=volume) for i in range(n)]


class TestCalculate:
    def test_less_than_50_returns_empty(self):
        assert AlphaZoo.calculate(_klines(10)) == {}

    def test_50_plus_returns_all_factors(self):
        factors = AlphaZoo.calculate(_klines(60))
        assert len(factors) == len(AlphaZoo.ALL_FACTORS) == 23
        for name in AlphaZoo.ALL_FACTORS:
            assert name in factors

    def test_values_are_floats(self):
        factors = AlphaZoo.calculate(_klines(60))
        for v in factors.values():
            assert isinstance(v, float)

    def test_constant_series(self):
        """全常數序列 → 無除零, 返回有限值."""
        factors = AlphaZoo.calculate(_klines(60, step=0.0))
        for v in factors.values():
            assert v == v  # 非 NaN


class TestMomentum:
    def test_momentum_12_1(self):
        closes = [100.0 + i for i in range(20)]
        # close[-1]=119, close[-13]=107, close[-2]=118
        m12 = (119 - 107) / 107
        m1 = (119 - 118) / 118
        assert AlphaZoo._momentum_12_1(closes) == pytest.approx(m12 - m1)

    def test_momentum_12_1_short(self):
        assert AlphaZoo._momentum_12_1([1.0, 2.0]) == 0.0

    def test_momentum_weighted_short(self):
        assert AlphaZoo._momentum_weighted([1.0] * 10) == 0.0

    def test_momentum_weighted_constant(self):
        """常數序列 → 每項 ratio=1 → 回報 0."""
        assert AlphaZoo._momentum_weighted([5.0] * 25) == pytest.approx(0.0)

    def test_rate_of_change(self):
        closes = [100.0 + i for i in range(15)]
        assert AlphaZoo._rate_of_change(closes, 12) == pytest.approx((114 - 102) / 102)

    def test_rate_of_change_short(self):
        assert AlphaZoo._rate_of_change([1.0, 2.0], 12) == 0.0

    def test_price_distance(self):
        closes = [100.0 + i for i in range(25)]  # 最後 20: 105..124
        # (124 - 105) / (124 - 105) = 1.0
        assert AlphaZoo._price_distance(closes) == pytest.approx(1.0)

    def test_price_distance_short_returns_midpoint(self):
        assert AlphaZoo._price_distance([1.0, 2.0]) == 0.5

    def test_price_distance_flat(self):
        assert AlphaZoo._price_distance([5.0] * 25) == 0.5

    def test_trend_strength_linear(self):
        """完美線性 → R²=1."""
        closes = [100.0 + i for i in range(30)]
        assert AlphaZoo._trend_strength(closes) == pytest.approx(1.0, abs=1e-6)

    def test_trend_strength_short(self):
        assert AlphaZoo._trend_strength([1.0] * 10) == 0.0

    def test_trend_strength_flat(self):
        assert AlphaZoo._trend_strength([5.0] * 30) == 0.0


class TestVolatility:
    def test_realized_volatility(self):
        closes = [100.0 + i for i in range(25)]
        v = AlphaZoo._realized_volatility(closes)
        assert v > 0.0  # 遞增序列有正波動

    def test_realized_volatility_short(self):
        assert AlphaZoo._realized_volatility([1.0] * 10) == 0.0

    def test_realized_volatility_constant(self):
        assert AlphaZoo._realized_volatility([5.0] * 30) == 0.0

    def test_volatility_ratio_short(self):
        assert AlphaZoo._volatility_ratio([1.0] * 10) == 1.0

    def test_volatility_ratio_constant(self):
        assert AlphaZoo._volatility_ratio([5.0] * 60) == 1.0  # long_vol=0 → 1.0

    def test_parkinson_volatility(self):
        highs = [110.0 + i for i in range(25)]
        lows = [90.0 + i for i in range(25)]
        assert AlphaZoo._parkinson_volatility(highs, lows) > 0.0

    def test_parkinson_volatility_short(self):
        assert AlphaZoo._parkinson_volatility([1.0], [1.0]) == 0.0

    def test_garman_klass_volatility(self):
        highs = [110.0 + i for i in range(25)]
        lows = [90.0 + i for i in range(25)]
        closes = [100.0 + i for i in range(25)]
        assert AlphaZoo._garman_klass_volatility(highs, lows, closes) > 0.0

    def test_garman_klass_short(self):
        assert AlphaZoo._garman_klass_volatility([1.0], [1.0], [1.0]) == 0.0

    def test_volatility_skew(self):
        """混合漲跌 → 正 skew."""
        closes = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.5, 104.0]
        closes += [104.0 + i for i in range(15)]
        v = AlphaZoo._volatility_skew(closes)
        assert v > 0.0

    def test_volatility_skew_short(self):
        assert AlphaZoo._volatility_skew([1.0] * 5) == 0.0

    def test_volatility_skew_all_positive(self):
        closes = [100.0 + i for i in range(25)]
        assert AlphaZoo._volatility_skew(closes) == 0.0  # 無 downside → 0


class TestVolume:
    def test_volume_ratio(self):
        volumes = [100.0] * 25
        assert AlphaZoo._volume_ratio(volumes) == pytest.approx(1.0)

    def test_volume_ratio_short(self):
        assert AlphaZoo._volume_ratio([1.0] * 5) == 1.0

    def test_volume_ratio_zero_avg(self):
        assert AlphaZoo._volume_ratio([0.0] * 25) == 1.0

    def test_obv_up_trend(self):
        closes = [100.0 + i for i in range(25)]
        volumes = [10.0] * 25
        # 全上升 → obv 累加正
        assert AlphaZoo._obv(closes, volumes) > 0.0

    def test_obv_short(self):
        assert AlphaZoo._obv([1.0] * 10, [1.0] * 10) == 0.0

    def test_obv_zero_volume(self):
        closes = [100.0 + i for i in range(25)]
        assert AlphaZoo._obv(closes, [0.0] * 25) == 0.0

    def test_vwap(self):
        highs = [110.0 + i for i in range(25)]
        lows = [90.0 + i for i in range(25)]
        closes = [100.0 + i for i in range(25)]
        volumes = [10.0] * 25
        v = AlphaZoo._vwap(highs, lows, closes, volumes)
        assert v > 0.0

    def test_vwap_short(self):
        assert AlphaZoo._vwap([1.0], [1.0], [1.0], [1.0]) == 1.0

    def test_vwap_zero_volume(self):
        highs = [110.0 + i for i in range(25)]
        lows = [90.0 + i for i in range(25)]
        closes = [100.0 + i for i in range(25)]
        assert AlphaZoo._vwap(highs, lows, closes, [0.0] * 25) == 1.0

    def test_volume_price_trend(self):
        closes = [100.0 + i for i in range(25)]
        volumes = [10.0] * 25
        assert AlphaZoo._volume_price_trend(closes, volumes) > 0.0

    def test_volume_price_trend_short(self):
        assert AlphaZoo._volume_price_trend([1.0] * 10, [1.0] * 10) == 0.0

    def test_money_flow_index_short(self):
        assert AlphaZoo._money_flow_index([1.0], [1.0], [1.0], [1.0]) == 50.0

    def test_money_flow_index_up(self):
        highs = [110.0 + i for i in range(20)]
        lows = [90.0 + i for i in range(20)]
        closes = [100.0 + i for i in range(20)]
        volumes = [10.0] * 20
        assert AlphaZoo._money_flow_index(highs, lows, closes, volumes) > 50.0

    def test_money_flow_index_no_negative(self):
        """全上升 → negative_flow=0 → 100."""
        highs = [110.0 + i for i in range(20)]
        lows = [90.0 + i for i in range(20)]
        closes = [100.0 + i for i in range(20)]
        assert AlphaZoo._money_flow_index(highs, lows, closes, [10.0] * 20) == 100.0

    def test_volume_volatility(self):
        volumes = [100.0] * 25
        assert AlphaZoo._volume_volatility(volumes) == 0.0  # 常數 → CV=0

    def test_volume_volatility_short(self):
        assert AlphaZoo._volume_volatility([1.0] * 5) == 0.0

    def test_volume_volatility_zero(self):
        assert AlphaZoo._volume_volatility([0.0] * 25) == 0.0


class TestMeanReversion:
    def test_rsi_zscore(self):
        assert AlphaZoo._rsi_zscore(50) == 0.0
        assert AlphaZoo._rsi_zscore(75) == pytest.approx(1.0)
        assert AlphaZoo._rsi_zscore(25) == pytest.approx(-1.0)

    def test_bollinger_band_width(self):
        indicators = {"bollinger_upper": 110.0, "bollinger_middle": 100.0, "bollinger_lower": 90.0}
        assert AlphaZoo._bollinger_band_width(indicators) == pytest.approx(0.2)

    def test_bollinger_band_width_zero_middle(self):
        assert AlphaZoo._bollinger_band_width({}) == 0.0

    def test_price_to_ma(self):
        assert AlphaZoo._price_to_ma([110.0], 100.0) == pytest.approx(0.1)

    def test_price_to_ma_zero(self):
        assert AlphaZoo._price_to_ma([110.0], 0.0) == 0.0

    def test_stochastic_oscillator(self):
        highs = [110.0 + i for i in range(20)]
        lows = [90.0 + i for i in range(20)]
        closes = [105.0 + i for i in range(20)]
        v = AlphaZoo._stochastic_oscillator(highs, lows, closes)
        assert 0.0 <= v <= 100.0

    def test_stochastic_short(self):
        assert AlphaZoo._stochastic_oscillator([1.0], [1.0], [1.0]) == 50.0

    def test_stochastic_flat(self):
        highs = [100.0] * 20
        lows = [90.0] * 20
        closes = [95.0] * 20
        assert AlphaZoo._stochastic_oscillator(highs, lows, closes) == 50.0

    def test_cci(self):
        highs = [110.0 + i for i in range(25)]
        lows = [90.0 + i for i in range(25)]
        closes = [100.0 + i for i in range(25)]
        assert AlphaZoo._cci(highs, lows, closes) != 0.0

    def test_cci_short(self):
        assert AlphaZoo._cci([1.0], [1.0], [1.0]) == 0.0

    def test_cci_flat(self):
        highs = [100.0] * 25
        lows = [90.0] * 25
        closes = [95.0] * 25
        assert AlphaZoo._cci(highs, lows, closes) == 0.0
