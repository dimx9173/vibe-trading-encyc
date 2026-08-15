"""Tests for backtest/metrics (Wave D — coverage 85% plan)."""

import pytest

from vibe_trading.backtest.metrics import (
    annualized_return,
    calculate_all_metrics,
    cumulative_return,
    maximum_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)


class TestCumulativeReturn:
    def test_basic(self):
        assert cumulative_return([100, 110, 120]) == pytest.approx(0.2)

    def test_short(self):
        assert cumulative_return([]) == 0.0
        assert cumulative_return([100]) == 0.0

    def test_zero_initial(self):
        assert cumulative_return([0, 10]) == 0.0


class TestAnnualizedReturn:
    def test_basic(self):
        # 100 → 121 in 2 periods, 252 ppy → (1.21)^126 - 1
        r = annualized_return([100, 110, 121], periods_per_year=252)
        assert r > 0

    def test_short(self):
        assert annualized_return([]) == 0.0
        assert annualized_return([100]) == 0.0


class TestSharpe:
    def test_positive_returns(self):
        r = sharpe_ratio([0.01, 0.02, 0.015, 0.01, 0.02], periods_per_year=252)
        assert r > 0

    def test_short(self):
        assert sharpe_ratio([]) == 0.0
        assert sharpe_ratio([0.01]) == 0.0

    def test_zero_volatility(self):
        assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0


class TestSortino:
    def test_no_downside_returns_inf(self):
        assert sortino_ratio([0.01, 0.02, 0.015]) == float("inf")

    def test_mixed(self):
        r = sortino_ratio([0.01, -0.01, 0.02, -0.005], periods_per_year=252)
        assert r > 0

    def test_short(self):
        assert sortino_ratio([]) == 0.0


class TestMaxDrawdown:
    def test_basic(self):
        # peak 120, trough 90 → (120-90)/120 = 0.25
        assert maximum_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)

    def test_short(self):
        assert maximum_drawdown([]) == 0.0
        assert maximum_drawdown([100]) == 0.0

    def test_no_drawdown(self):
        assert maximum_drawdown([100, 110, 120]) == 0.0


class TestWinRate:
    def test_basic(self):
        trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": -3}]
        assert win_rate(trades) == 0.5

    def test_empty(self):
        assert win_rate([]) == 0.0


class TestProfitFactor:
    def test_basic(self):
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 50}]
        assert profit_factor(trades) == pytest.approx(3.0)

    def test_empty(self):
        assert profit_factor([]) == 0.0

    def test_no_losses(self):
        assert profit_factor([{"pnl": 10}, {"pnl": 5}]) == float("inf")


class TestCalculateAll:
    def test_empty(self):
        m = calculate_all_metrics([], [])
        assert m["cumulative_return"] == 0.0
        assert m["win_rate"] == 0.0

    def test_full(self):
        equity = [100, 105, 103, 110, 108]
        trades = [{"pnl": 10}, {"pnl": -4}, {"pnl": 6}]
        m = calculate_all_metrics(equity, trades)
        assert m["cumulative_return"] == pytest.approx(0.08)
        assert m["win_rate"] == pytest.approx(2 / 3)
        assert m["maximum_drawdown"] > 0
        assert m["profit_factor"] > 1.0
