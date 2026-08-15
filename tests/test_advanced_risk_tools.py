"""Tests for execution/advanced_risk_tools (Wave D — coverage 85% plan).

VaR/Kelly/RiskMetrics 都是純邏輯計算器 — 直接測數值.
"""
from datetime import datetime, timedelta

import pytest

from vibe_trading.execution.advanced_risk_tools import (
    KellyCalculator,
    RiskMetricsCalculator,
    VaRCalculator,
)


class TestVaRCalculator:
    def test_insufficient_data_defaults(self):
        c = VaRCalculator()
        r = c.calculate_var(10000.0)
        assert r.var_95 == 10000.0 * 0.02
        assert r.var_99 == 10000.0 * 0.03

    def test_historical_var(self):
        c = VaRCalculator()
        for i in range(20):
            c.add_price_change(100.0 + i, 100.0 + i + 1)  # 穩定上升
        r = c.calculate_var(10000.0, method="historical")
        assert r.var_95 >= 0
        assert r.volatility >= 0

    def test_parametric_var(self):
        c = VaRCalculator()
        for i in range(20):
            c.add_price_change(100.0 + i, 100.0 + i + 1)
        r = c.calculate_var(10000.0, method="parametric")
        assert r.var_95 >= 0
        assert r.confidence_interval[0] <= r.confidence_interval[1]

    def test_add_return(self):
        c = VaRCalculator()
        c.add_return(0.01)
        c.add_return(-0.02)
        assert len(c._returns_history) == 2

    def test_default_method_falls_to_historical(self):
        c = VaRCalculator()
        for i in range(15):
            c.add_return(0.01)
        r = c.calculate_var(1000.0, method="monte_carlo")
        assert r.var_95 > 0


class TestKellyCalculator:
    def test_insufficient_trades_conservative(self):
        k = KellyCalculator()
        r = k.calculate_kelly(10000.0, min_trades=10)
        assert r.kelly_fraction == 0.02
        assert r.optimal_position_size == 200.0

    def test_profitable_trades(self):
        k = KellyCalculator()
        for i in range(12):
            k.add_trade(pnl=100.0, entry_price=100.0, exit_price=110.0,
                        position_size=10.0)
        r = k.calculate_kelly(10000.0, min_trades=10)
        assert r.win_rate == 1.0
        assert r.kelly_fraction > 0
        assert r.half_kelly_fraction == r.kelly_fraction / 2

    def test_mixed_trades(self):
        k = KellyCalculator()
        for i in range(6):
            k.add_trade(pnl=100.0, entry_price=100.0, exit_price=110.0,
                        position_size=10.0)
        for i in range(6):
            k.add_trade(pnl=-50.0, entry_price=100.0, exit_price=95.0,
                        position_size=10.0)
        r = k.calculate_kelly(10000.0, min_trades=10)
        assert r.win_rate == 0.5
        assert r.avg_win == 100.0
        assert r.avg_loss == 50.0
        assert r.profit_factor == 2.0
        assert 0 < r.kelly_fraction <= 0.25

    def test_add_trade_zero_entry(self):
        k = KellyCalculator()
        k.add_trade(pnl=10.0, entry_price=0.0, exit_price=10.0, position_size=1.0)
        assert k._trade_history[0]["return"] == 0


class TestRiskMetricsCalculator:
    def test_metrics_empty(self):
        c = RiskMetricsCalculator()
        m = c.calculate_metrics(10000.0, 10000.0, 0.0, 1000.0, 9000.0)
        assert m.margin_ratio == 0.1
        assert m.max_drawdown == 0
        assert m.total_trades == 0
        assert m.win_rate == 0
        assert m.var_95 == 200.0  # 10% 不足 → equity * 0.02

    def test_update_balance_and_peak(self):
        c = RiskMetricsCalculator()
        c.update_balance(10000.0, 10000.0)
        c.update_balance(9000.0, 9500.0)
        assert c._peak_equity == 10000.0
        m = c.calculate_metrics(10000.0, 9500.0, 0, 0, 10000.0)
        assert m.current_drawdown == pytest.approx(0.05)

    def test_trades_stats(self):
        c = RiskMetricsCalculator()
        now = datetime.now()
        for i in range(5):
            c.add_trade(pnl=100.0, entry_price=100.0, exit_price=110.0,
                        position_size=1.0, symbol="BTCUSDT",
                        entry_time=now, exit_time=now + timedelta(hours=1))
        for i in range(5):
            c.add_trade(pnl=-50.0, entry_price=100.0, exit_price=95.0,
                        position_size=1.0, symbol="BTCUSDT",
                        entry_time=now, exit_time=now + timedelta(hours=1))
        m = c.calculate_metrics(10000.0, 10000.0, 0, 1000, 9000)
        assert m.total_trades == 10
        assert m.winning_trades == 5
        assert m.win_rate == 0.5
        assert m.realized_pnl == 250.0  # 5*100 - 5*50
        assert m.avg_win == 100.0

    def test_max_drawdown_calculation(self):
        c = RiskMetricsCalculator()
        for eq in [10000, 11000, 9500, 10500, 9000]:
            c.update_balance(eq, eq)
        m = c.calculate_metrics(10000.0, 9000.0, 0, 0, 10000)
        # peak=11000, 最低 9000 → (11000-9000)/11000 = 18.2%
        assert m.max_drawdown == pytest.approx(0.1818, abs=0.001)

    def test_consecutive_losses(self):
        c = RiskMetricsCalculator()
        now = datetime.now()
        for i in range(3):
            c.add_trade(pnl=-10.0, entry_price=100.0, exit_price=99.0,
                        position_size=1.0, symbol="X",
                        entry_time=now, exit_time=now)
        m = c.calculate_metrics(10000.0, 10000.0, 0, 0, 10000)
        assert m.consecutive_losses == 3
        assert m.max_losing_streak == 3

    def test_streak_tracking(self):
        c = RiskMetricsCalculator()
        now = datetime.now()
        c.add_trade(pnl=10.0, entry_price=1.0, exit_price=2.0, position_size=1.0,
                    symbol="X", entry_time=now, exit_time=now)
        c.add_trade(pnl=-5.0, entry_price=1.0, exit_price=0.5, position_size=1.0,
                    symbol="X", entry_time=now, exit_time=now)
        m = c.calculate_metrics(10000.0, 10000.0, 0, 0, 10000)
        assert m.current_streak == -1  # 最後一筆虧損


class TestRiskLevelAssessment:
    def test_assess_risk_level_consecutive_losses(self):
        from vibe_trading.execution.advanced_risk_tools import RiskMetricsCalculator
        c = RiskMetricsCalculator()
        level, warnings = c._assess_risk_level(
            current_drawdown=0.1, max_drawdown=0.2, margin_ratio=0.5,
            consecutive_losses=5,
        )
        assert level == "critical"
        assert len(warnings) >= 1

    def test_assess_risk_level_3_losses(self):
        from vibe_trading.execution.advanced_risk_tools import RiskMetricsCalculator
        c = RiskMetricsCalculator()
        level, warnings = c._assess_risk_level(
            current_drawdown=0.1, max_drawdown=0.2, margin_ratio=0.5,
            consecutive_losses=3,
        )
        assert level == "high"


class TestVolatilitySizer:
    def test_basic_size(self):
        from vibe_trading.execution.advanced_risk_tools import VolatilityAdjustedPositionSizer
        s = VolatilityAdjustedPositionSizer(base_risk_per_trade=0.02)
        size = s.calculate_adjusted_position_size(10000.0, 100.0, 98.0)
        assert size == 3000.0  # cap 30%

    def test_zero_stop_distance(self):
        from vibe_trading.execution.advanced_risk_tools import VolatilityAdjustedPositionSizer
        s = VolatilityAdjustedPositionSizer()
        assert s.calculate_adjusted_position_size(10000.0, 100.0, 100.0) == 100.0

    def test_high_volatility_reduces(self):
        from vibe_trading.execution.advanced_risk_tools import VolatilityAdjustedPositionSizer
        s = VolatilityAdjustedPositionSizer()
        for i in range(10):
            s.update_atr(1.0, 100.0)
        # stop 距離 20% → base = 200/0.2 = 1000 (< cap 3000) → 調整後 500
        size = s.calculate_adjusted_position_size(10000.0, 100.0, 80.0, current_atr=5.0)
        assert size == 500.0  # 1000 * 0.5

    def test_low_volatility_capped(self):
        from vibe_trading.execution.advanced_risk_tools import VolatilityAdjustedPositionSizer
        s = VolatilityAdjustedPositionSizer()
        for i in range(10):
            s.update_atr(5.0, 100.0)
        size = s.calculate_adjusted_position_size(10000.0, 100.0, 80.0, current_atr=1.0)
        assert size == 1200.0  # 1000 * 1.2

    def test_update_atr(self):
        from vibe_trading.execution.advanced_risk_tools import VolatilityAdjustedPositionSizer
        s = VolatilityAdjustedPositionSizer()
        s.update_atr(2.0, 100.0)
        assert len(s._atr_history) == 1


class TestCorrelationChecker:
    def test_update_and_correlate(self):
        from vibe_trading.execution.advanced_risk_tools import CorrelationRiskChecker
        c = CorrelationRiskChecker()
        for i in range(20):
            c.update_price("A", 100.0 + i)
            c.update_price("B", 200.0 + 2 * i)
        corr = c.calculate_correlation("A", "B")
        assert corr > 0.9

    def test_missing_symbol(self):
        from vibe_trading.execution.advanced_risk_tools import CorrelationRiskChecker
        c = CorrelationRiskChecker()
        assert c.calculate_correlation("A", "B") == 0.0

    def test_insufficient_data(self):
        from vibe_trading.execution.advanced_risk_tools import CorrelationRiskChecker
        c = CorrelationRiskChecker()
        for i in range(5):
            c.update_price("A", 100.0 + i)
            c.update_price("B", 100.0 + i)
        assert c.calculate_correlation("A", "B") == 0.0

    def test_check_portfolio_correlation(self):
        from vibe_trading.execution.advanced_risk_tools import CorrelationRiskChecker
        c = CorrelationRiskChecker()
        for i in range(20):
            c.update_price("A", 100.0 + i)
            c.update_price("B", 100.0 + i)
            c.update_price("C", 100.0 - i)
        result = c.check_portfolio_correlation(["A", "B", "C"], threshold=0.7)
        assert "A" in result


class TestTrailingStop:
    def test_long_trailing_stop(self):
        from vibe_trading.execution.advanced_risk_tools import TrailingStopLossManager
        t = TrailingStopLossManager(activation_profit_pct=0.01, trail_distance_pct=0.02)
        t.add_position("BTCUSDT", 100.0, "LONG", 95.0)
        assert t.update_stop_loss("BTCUSDT", 100.5) is None  # 未激活
        new_stop = t.update_stop_loss("BTCUSDT", 103.0)
        assert new_stop is not None
        assert new_stop > 95.0
        assert t.update_stop_loss("BTCUSDT", 102.0) is None  # 不向下

    def test_short_trailing_stop(self):
        from vibe_trading.execution.advanced_risk_tools import TrailingStopLossManager
        t = TrailingStopLossManager(activation_profit_pct=0.01, trail_distance_pct=0.02)
        t.add_position("BTCUSDT", 100.0, "SHORT", 105.0)
        assert t.update_stop_loss("BTCUSDT", 96.0) is not None

    def test_unknown_symbol(self):
        from vibe_trading.execution.advanced_risk_tools import TrailingStopLossManager
        t = TrailingStopLossManager()
        assert t.update_stop_loss("NOPE", 100.0) is None
        assert t.get_stop_loss("NOPE") is None

    def test_get_remove(self):
        from vibe_trading.execution.advanced_risk_tools import TrailingStopLossManager
        t = TrailingStopLossManager()
        t.add_position("BTCUSDT", 100.0, "LONG", 95.0)
        assert t.get_stop_loss("BTCUSDT") == 95.0
        t.remove_position("BTCUSDT")
        assert t.get_stop_loss("BTCUSDT") is None
