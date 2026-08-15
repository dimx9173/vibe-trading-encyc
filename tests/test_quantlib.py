"""Tests for quantlib (Roadmap Phase 1.1) — deterministic finance math library."""
import numpy as np
import pytest

from vibe_trading.quantlib.capital import (
    fractional_kelly,
    max_drawdown_limit,
    twr,
    xirr,
)
from vibe_trading.quantlib.impact import (
    estimate_impact_cost,
    estimated_slippage_bps,
)
from vibe_trading.quantlib.risk import (
    _norm_ppf,
    calculate_var,
    ewma_volatility,
    garch11_volatility,
)


def _returns(n=200, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.02, n)


# === risk: VaR ===

class TestVaR:
    def test_historical(self):
        r = calculate_var(_returns(), 10000, method="historical")
        assert 0 < r.var_95 < r.var_99
        assert r.cvar_95 > 0
        assert r.method == "historical"

    def test_parametric_no_scipy(self):
        # 純 numpy 計算, 不應 ImportError
        r = calculate_var(_returns(), 10000, method="parametric")
        assert r.var_95 > 0
        assert r.method == "parametric"

    def test_cornish_fisher_skewed_direction(self):
        # 正偏 returns → VaR 低於正態 (CF 修正方向)
        rng = np.random.default_rng(7)
        skewed = rng.gamma(2.0, 0.01, 500) - 0.02  # 右偏
        cf = calculate_var(skewed, 10000, method="cornish_fisher")
        param = calculate_var(skewed, 10000, method="parametric")
        assert cf.var_95 < param.var_95  # 正偏 → 左尾更薄

    def test_evt_fallback(self):
        # 樣本不足 (<20 超閾值) → 回退 (不 raise)
        small = _returns(n=15)
        r = calculate_var(small, 10000, method="evt")
        assert r.var_95 > 0

    def test_insufficient_samples_fallback(self):
        r = calculate_var(np.array([0.01, -0.01]), 10000)
        assert r.var_95 > 0  # 回退固定值

    def test_norm_ppf_accuracy(self):
        assert abs(_norm_ppf(0.95) - 1.6448536) < 1e-4
        assert abs(_norm_ppf(0.99) - 2.3263478) < 1e-4
        assert abs(_norm_ppf(0.5) - 0.0) < 1e-4


# === risk: volatility ===

class TestVolatility:
    def test_ewma_constant_returns_tends_to_zero(self):
        r = np.full(100, 0.001)
        vol = ewma_volatility(r)
        assert vol < 0.01  # 常數微正 → vol 趨近 0

    def test_ewma_increasing_volatility(self):
        rng = np.random.default_rng(1)
        low = rng.normal(0, 0.005, 100)
        high = rng.normal(0, 0.05, 100)
        vol_low = ewma_volatility(low)
        vol_high = ewma_volatility(high)
        assert vol_high > vol_low * 3

    def test_garch11_constant(self):
        r = np.full(200, 0.01)
        vol, series = garch11_volatility(r)
        assert vol < 0.02
        assert len(series) == 200
        assert np.all(series > 0)

    def test_garch11_variance_targeting(self):
        rng = np.random.default_rng(3)
        r = rng.normal(0, 0.03, 500)
        vol, _ = garch11_volatility(r)
        assert 0.02 < vol < 0.05  # 收斂至長期變異數附近


# === capital ===

class TestCapital:
    def test_fractional_kelly(self):
        assert abs(fractional_kelly(0.6, 2.0) - 0.2) < 1e-9  # 0.5*(0.6-0.4/2)

    def test_kelly_edge(self):
        assert fractional_kelly(1.0, 2.0) == 0.0  # p=1 → 無意義
        assert fractional_kelly(0.5, 0.0) == 0.0  # payoff=0
        assert fractional_kelly(0.2, 1.0) == 0.0  # 期望負 → 不投注

    def test_max_drawdown_limit(self):
        assert max_drawdown_limit(0.5, 0.2, 0.0) == 0.5
        assert abs(max_drawdown_limit(0.5, 0.2, 0.1) - 0.25) < 1e-9
        assert max_drawdown_limit(0.5, 0.2, 0.3) == 0.0

    def test_twr(self):
        r = np.array([0.1, -0.05, 0.02])
        assert abs(twr(r) - (1.1 * 0.95 * 1.02 - 1)) < 1e-9

    def test_twr_empty(self):
        assert twr(np.array([])) == 0.0

    def test_xirr_single_cashflow(self):
        # 投 1000, 1 年後 1100 → IRR 10%
        irr = xirr([(0.0, -1000.0), (1.0, 1100.0)])
        assert abs(irr - 0.10) < 1e-4

    def test_xirr_invest_now_pay_later(self):
        # 投 5000, 2 年後 6050 → ~10%
        irr = xirr([(0.0, -5000.0), (2.0, 6050.0)])
        assert abs(irr - 0.10) < 1e-3


# === impact ===

class TestImpact:
    def test_depth_sufficient(self):
        levels = [(100.0, 0.3), (100.5, 0.3), (101.0, 0.4)]
        r = estimate_impact_cost(levels, 0.5, 100.0)
        assert r["filled_qty"] == pytest.approx(0.5)
        assert r["remaining_qty"] == 0.0
        assert r["insufficient_depth"] is False
        assert r["slippage_bps"] > 0

    def test_depth_insufficient(self):
        levels = [(100.0, 0.2)]
        r = estimate_impact_cost(levels, 0.5, 100.0)
        assert r["remaining_qty"] == pytest.approx(0.3)
        assert r["insufficient_depth"] is True

    def test_no_depth(self):
        r = estimate_impact_cost([], 0.5, 100.0)
        assert r["filled_qty"] == 0.0
        assert r["remaining_qty"] == pytest.approx(0.5)
        assert r["insufficient_depth"] is True

    def test_zero_order(self):
        r = estimate_impact_cost([(100.0, 0.5)], 0.0, 100.0)
        assert r["slippage_bps"] == 0.0

    def test_slippage_model(self):
        assert abs(estimated_slippage_bps(1.0, 100.0) - 99.0099) < 0.1
        assert estimated_slippage_bps(0.0, 100.0) == 0.0
        assert estimated_slippage_bps(1.0, 0.0) == 0.0


# === advanced_risk_tools scipy fix ===

class TestScipyFix:
    def test_parametric_var_no_scipy(self):
        from vibe_trading.execution.advanced_risk_tools import VaRCalculator

        v = VaRCalculator()
        for i in range(50):
            v.add_return(0.01 if i % 2 else -0.005)
        result = v.calculate_var(10000, method="parametric")
        assert result.var_95 > 0  # 不再 ImportError


# === risk_manager quantlib wiring ===

class TestRiskManagerQuantlib:
    def test_assess_overall_risk_has_quantlib(self):
        from vibe_trading.execution.risk_manager import RiskManager

        rm = RiskManager()
        # 餵入一些交易歷史
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 8, 1, tzinfo=timezone.utc)
        for i in range(10):
            rm.record_trade(
                pnl=5.0 if i % 2 else -3.0,
                entry_price=100.0,
                exit_price=100.0 + i * 0.5,
                position_size=100.0,
                symbol="BTCUSDT",
                entry_time=base + timedelta(hours=i),
                exit_time=base + timedelta(hours=i + 1),
            )
        result = rm.assess_overall_risk(
            account_balance=10000.0, total_equity=10000.0,
            margin_used=100.0, margin_free=9900.0,
            positions=[{"unrealized_profit": 0.0}],
        )
        assert "quantlib" in result
        q = result["quantlib"]
        # 交易次數 ≥5 → kelly 應存在 (可能為 0, 但鍵存在)
        assert "kelly_fraction" in q
