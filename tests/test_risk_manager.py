"""
Test for execution/risk_manager.py

Risk manager is the core safety gate (SWDA attack point #2).
Tests cover: order risk check, position sizing, stop-loss / take-profit math,
leverage validation, and risk limit reporting.
"""
from unittest.mock import patch

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, PositionSide
from vibe_trading.execution.risk_manager import (
    PositionRiskInfo,
    RiskCheck,
    RiskCheckResult,
    RiskManager,
)


# Mock settings so RiskManager has large enough limits to test all paths.
# The production defaults (0.1 USDT, 0.02 stop) are too tight for meaningful tests.
def _mock_settings():
    """Settings that allow normal test orders + reasonable risk ratios."""
    from dataclasses import dataclass
    @dataclass
    class _S:
        max_position_size: float = 10000.0      # 10k USDT per order
        max_total_position: float = 50000.0     # 50k USDT total
        stop_loss_pct: float = 0.02             # 2%
        take_profit_pct: float = 0.05           # 5%
        leverage: int = 5
    return _S()


@pytest.fixture
def rm():
    """RiskManager with mocked settings (10k/50k/2%/5%/5x)."""
    with patch("vibe_trading.execution.risk_manager.get_settings", _mock_settings):
        yield RiskManager()


# === Enum / dataclass tests ===

class TestDataclasses:
    def test_risk_check_result_values(self):
        # str, Enum — values must be uppercase strings
        assert RiskCheckResult.APPROVED.value == "approved"
        assert RiskCheckResult.REJECTED.value == "rejected"
        assert RiskCheckResult.WARNING.value == "warning"

    def test_risk_check_post_init_warnings_default(self):
        # If no warnings passed, must default to empty list (not None)
        rc = RiskCheck(result=RiskCheckResult.APPROVED, reason="ok")
        assert rc.warnings == []

    def test_risk_check_explicit_warnings_kept(self):
        rc = RiskCheck(
            result=RiskCheckResult.WARNING,
            reason="risky",
            warnings=["VaR high"]
        )
        assert rc.warnings == ["VaR high"]

    def test_position_risk_info_construction(self):
        pri = PositionRiskInfo(
            symbol="BTCUSDT",
            entry_price=100.0,
            current_price=101.0,
            position_size=1.0,
            position_side="LONG",
            unrealized_pnl=1.0,
            unrealized_pnl_pct=0.01,
            stop_loss=98.0,
            take_profit=105.0,
        )
        assert pri.symbol == "BTCUSDT"
        # Defaults
        assert pri.liquidation_price is None
        assert pri.margin_ratio == 0
        assert pri.risk_score == 0


# === check_order_risk (async) ===

class TestCheckOrderRisk:
    async def test_small_order_approved(self, rm):
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.01,
            price=50000.0,
            current_balance=100000.0,
        )
        assert rc.result == RiskCheckResult.APPROVED
        assert rc.warnings == []

    async def test_order_exceeds_max_position_size_rejected(self, rm):
        # max_position_size=10000 → use quantity=1 @ price=50000 → order_value=50000
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=1.0,
            price=50000.0,
        )
        assert rc.result == RiskCheckResult.REJECTED
        assert "超过最大" in rc.reason or "max" in rc.reason.lower()

    async def test_order_exceeds_total_position_rejected(self, rm):
        # Already have 45k exposure, new order of 10k → 55k > 50k limit
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.1,
            price=100000.0,
            current_balance=200000.0,
            current_positions={"total_exposure": 45000.0},
        )
        assert rc.result == RiskCheckResult.REJECTED

    async def test_margin_above_50pct_rejected(self, rm):
        # Need order_value > 0.5 * leverage * balance
        # With balance=1000, leverage=5: order_value > 2500
        # Use order_value=3000 (< max_position_size=10000)
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.03,
            price=100000.0,  # order_value=3000
            current_balance=1000.0,
        )
        # 3000 / 5 = 600 required margin / 1000 balance = 60% > 50%
        assert rc.result == RiskCheckResult.REJECTED
        assert "保证金" in rc.reason or "margin" in rc.reason.lower()

    async def test_margin_30_to_50pct_warns(self, rm):
        # balance=1000, order_value=2000 → margin=400/1000=40% → WARNING
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.02,
            price=100000.0,
            current_balance=1000.0,
        )
        assert rc.result == RiskCheckResult.WARNING
        assert len(rc.warnings) > 0

    async def test_no_price_uses_default_50k(self, rm):
        # when price=None, order_value = quantity * 50000
        # quantity=0.1 → 5000 USDT, well within limits
        rc = await rm.check_order_risk(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.1,
            price=None,
        )
        assert rc.result == RiskCheckResult.APPROVED


# === calculate_position_size ===

class TestCalculatePositionSize:
    def test_basic_2pct_risk(self, rm):
        # entry=100, stop=98 → stop_distance=2%
        # 2% risk on 10000 balance = 200 USDT
        # position_value = 200 / 0.02 = 10000, capped at 10000
        # size = 10000 / 100 = 100
        size = rm.calculate_position_size(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss_price=98.0,
            account_balance=10000.0,
        )
        assert abs(size - 100.0) < 0.01

    def test_zero_stop_distance_returns_max_size(self, rm):
        # No stop distance → should return max_position_size / entry_price
        size = rm.calculate_position_size(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss_price=100.0,  # same as entry
            account_balance=10000.0,
        )
        # max_position_size / entry_price = 10000 / 100 = 100
        assert abs(size - 100.0) < 0.01

    def test_result_capped_at_max_position_size(self, rm):
        # 2% risk on 100k balance = 2000 USDT
        # stop_distance=0.01 → position_value = 2000/0.01 = 200000, capped at 10000
        size = rm.calculate_position_size(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss_price=99.0,
            account_balance=100000.0,
        )
        # capped at 10000/100 = 100
        assert abs(size - 100.0) < 0.01


# === calculate_stop_loss ===

class TestCalculateStopLoss:
    def test_long_uses_pct_stop(self, rm):
        # entry=100, stop_loss_pct=0.02 → stop = 100 - 2 = 98
        sl = rm.calculate_stop_loss(
            entry_price=100.0,
            position_side=PositionSide.LONG,
        )
        assert sl == 98.0

    def test_short_uses_pct_stop(self, rm):
        # entry=100, short → stop = 100 + 2 = 102
        sl = rm.calculate_stop_loss(
            entry_price=100.0,
            position_side=PositionSide.SHORT,
        )
        assert sl == 102.0

    def test_atr_overrides_pct_when_larger(self, rm):
        # entry=100, atr=10 → 2*ATR=20 > 2% entry=2 → uses 20
        sl = rm.calculate_stop_loss(
            entry_price=100.0,
            position_side=PositionSide.LONG,
            atr=10.0,
        )
        assert sl == 80.0

    def test_atr_overrides_pct_branch_uses_atr_2x(self, rm):
        # NOTE: when atr is given without volatility_adjusted, the code uses
        # atr*2 directly (no max() with stop_loss_pct). This is a known
        # characteristic — a small ATR causes a tight stop.
        # entry=100, atr=0.5 → stop_distance=1.0 → sl=99
        sl = rm.calculate_stop_loss(
            entry_price=100.0,
            position_side=PositionSide.LONG,
            atr=0.5,
        )
        assert sl == 99.0


# === calculate_take_profit ===

class TestCalculateTakeProfit:
    def test_long_with_default_risk_reward(self, rm):
        # No ATR → profit_distance = entry * take_profit_pct = 100 * 0.05 = 5
        # 2:1 R:R floor = 2 * 2 = 4
        # max(5, 4) = 5 → tp = 100 + 5 = 105
        tp = rm.calculate_take_profit(
            entry_price=100.0,
            position_side=PositionSide.LONG,
        )
        assert tp == 105.0

    def test_short_with_default_risk_reward(self, rm):
        tp = rm.calculate_take_profit(
            entry_price=100.0,
            position_side=PositionSide.SHORT,
        )
        assert tp == 95.0

    def test_atr_3x_enforced_when_larger_than_rr(self, rm):
        # entry=100, atr=10 → 3*ATR=30 > 4 (RR min) → uses 30
        tp = rm.calculate_take_profit(
            entry_price=100.0,
            position_side=PositionSide.LONG,
            atr=10.0,
        )
        assert tp == 130.0

    def test_atr_min_rr_floor(self, rm):
        # entry=100, atr=0.5 → 3*ATR=1.5 < 4 (RR min) → uses 4
        tp = rm.calculate_take_profit(
            entry_price=100.0,
            position_side=PositionSide.LONG,
            atr=0.5,
        )
        assert tp == 104.0

    def test_higher_rr_ratio_takes_max(self, rm):
        # 3:1 R:R → stop_distance=2, min_profit=6
        # use_pct=5% → 5 > 6? No, 5 < 6 → uses 6
        tp = rm.calculate_take_profit(
            entry_price=100.0,
            position_side=PositionSide.LONG,
            risk_reward_ratio=3.0,
        )
        assert tp == 106.0


# === validate_leverage ===

class TestValidateLeverage:
    def test_within_limit_accepted(self, rm):
        # max_leverage = settings.leverage = 5 → 1..5 valid
        assert rm.validate_leverage(1) is True
        assert rm.validate_leverage(5) is True

    def test_exceeds_limit_rejected(self, rm):
        assert rm.validate_leverage(125) is False
        assert rm.validate_leverage(1000) is False

    def test_zero_leverage_rejected(self, rm):
        # 0 is invalid
        assert rm.validate_leverage(0) is False


# === get_risk_limits / set_risk_limits ===

class TestRiskLimits:
    def test_get_returns_dict(self, rm):
        limits = rm.get_risk_limits()
        assert isinstance(limits, dict)
        assert "max_position_size" in limits
        assert "max_total_position" in limits
        assert "stop_loss_pct" in limits
        assert "take_profit_pct" in limits
        assert "max_leverage" in limits

    def test_get_reflects_settings(self, rm):
        limits = rm.get_risk_limits()
        assert limits["max_position_size"] == 10000.0
        assert limits["max_total_position"] == 50000.0
        assert limits["stop_loss_pct"] == 0.02
        assert limits["max_leverage"] == 5

    def test_set_updates_values(self, rm):
        rm.set_risk_limits(
            max_position_size=20000.0,
            stop_loss_pct=0.03,
        )
        limits = rm.get_risk_limits()
        assert limits["max_position_size"] == 20000.0
        assert limits["stop_loss_pct"] == 0.03
        # Unchanged
        assert limits["max_leverage"] == 5
