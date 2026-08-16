"""Tests for position sizing engine (Phase 5 — Half-Kelly + ATR)."""
import pytest

from vibe_trading.execution.position_sizing import (
    apply_risk_guardrails,
    calculate_actual_risk_reward,
    calculate_atr_position_size,
    calculate_half_kelly,
    calibrate_win_rate,
)


class TestHalfKelly:
    def test_positive_edge(self):
        # p=0.6, b=2 → f* = (2*0.6-0.4)/2 * 0.5 = 0.4*0.5 = 0.2
        assert calculate_half_kelly(0.6, 2.0) == pytest.approx(0.2)

    def test_no_edge_zero(self):
        # p=0.5, b=1 → f* = 0
        assert calculate_half_kelly(0.5, 1.0) == 0.0

    def test_negative_edge_zero(self):
        # p=0.4, b=1 → 負期望 → 0
        assert calculate_half_kelly(0.4, 1.0) == 0.0

    def test_invalid_inputs(self):
        assert calculate_half_kelly(0.0, 2.0) == 0.0
        assert calculate_half_kelly(0.6, 0.0) == 0.0
        assert calculate_half_kelly(1.0, 2.0) == 0.0  # p>=1 防呆


class TestRiskReward:
    def test_basic(self):
        assert calculate_actual_risk_reward(100, 90, 130) == pytest.approx(3.0)

    def test_zero_risk(self):
        assert calculate_actual_risk_reward(100, 100, 130) == 0.0

    def test_invalid(self):
        assert calculate_actual_risk_reward(0, 90, 130) == 0.0
        assert calculate_actual_risk_reward(100, 0, 130) == 0.0


class TestCalibrateWinRate:
    def test_mapping(self):
        assert calibrate_win_rate(0.5) == pytest.approx(0.5)
        assert calibrate_win_rate(0.75) == pytest.approx(0.6)
        assert calibrate_win_rate(0.25) == pytest.approx(0.4)

    def test_extremes(self):
        # p = 0.5 + (conf-0.5)*0.4 → conf=1.0 → 0.7 (clamp 上限 0.75 未觸及)
        assert calibrate_win_rate(1.0) == pytest.approx(0.7)
        # conf=0.0 → 0.3 → clamp 至 0.35
        assert calibrate_win_rate(0.0) == pytest.approx(0.35)


class TestATRPositionSize:
    def test_normal(self):
        # entry=100, SL=95, TP=115 → b=3; conf=0.7 → p=0.58
        # kelly = (3*0.58-0.42)/3*0.5 = (1.74-0.42)/3*0.5 = 0.22
        # dollar_risk = 10000*0.22 = 2200; atr=4 → effective_atr=4 → qty=2200/6=366.7
        # cap = min(500, 10000*5)/100 = 500/100 = 5 → min(366.7, 5) = 5
        qty = calculate_atr_position_size(
            account_equity=10000, confidence=0.7,
            entry_price=100, stop_loss_price=95, take_profit_price=115,
            atr_30m=4.0)
        assert qty == pytest.approx(5.0)  # 500U cap 截斷

    def test_high_atr_reduces(self):
        # 大 ATR → 數量縮小 (低價 entry 使 cap 不綁, atr 效果可見)
        q1 = calculate_atr_position_size(10000, 0.8, 100, 95, 130,
                                         atr_30m=4.0, max_single_notional=100000)
        q2 = calculate_atr_position_size(10000, 0.8, 100, 95, 130,
                                         atr_30m=20.0, max_single_notional=100000)
        assert q2 < q1

    def test_invalid_returns_zero(self):
        assert calculate_atr_position_size(0, 0.7, 100, 95, 115, 4.0) == 0.0
        assert calculate_atr_position_size(10000, 0.7, 0, 95, 115, 4.0) == 0.0
        # SL=entry → b=0 → 0
        assert calculate_atr_position_size(10000, 0.7, 100, 100, 115, 4.0) == 0.0

    def test_negative_edge_zero(self):
        # TP 太低 → b 小 → kelly 0
        assert calculate_atr_position_size(10000, 0.5, 100, 95, 101, 4.0) == 0.0

    def test_atr_floor(self):
        # atr 極小 → 用 entry*0.005 下限
        qty = calculate_atr_position_size(10000, 0.9, 100, 95, 130, atr_30m=0.001)
        assert qty > 0


class TestGuardrails:
    def test_cap_notional(self):
        assert apply_risk_guardrails(10.0, 100, 10000) == pytest.approx(5.0)  # 500/100

    def test_cap_leverage(self):
        # equity 低 → leverage cap 生效: min(500, 1000*5)/entry
        assert apply_risk_guardrails(10.0, 100, 1000) == pytest.approx(5.0)

    def test_invalid(self):
        assert apply_risk_guardrails(0, 100, 10000) == 0.0
        assert apply_risk_guardrails(1.0, 0, 10000) == 0.0
