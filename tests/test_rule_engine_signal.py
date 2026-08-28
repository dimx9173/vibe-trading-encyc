"""Tests for rule_engine/signal.py (spec phase1 §7: threshold boundaries, insufficiency, fake-breakout)."""
import math

import pytest

from vibe_trading.rule_engine.signal import (
    DEFAULT_ENTRY_THRESHOLD,
    RuleSignal,
    generate_signal,
    momentum_tanh_score,
)


def _boundary_factors(target_composite: float) -> dict:
    """Build a factors dict whose composite (via [1.0, y]) lands deterministically at target.

    momentum_tanh_score normalizes by (max|arr| + 1e-8); with values [1.0, y] that
    divisor is (1.0 + 1e-8). Invert so composite == target within ~1e-16.
    """
    scaled = 2.0 * math.atanh(target_composite) * (1.0 + 1e-8)
    return {"momentum_12_1": 1.0, "rate_of_change": scaled - 1.0}


def _short_factors(target_composite: float) -> dict:
    """Mirror for SHORT: values [-1.0, y2] so composite == target (negative)."""
    scaled = 2.0 * math.atanh(target_composite) * (1.0 + 1e-8)
    return {"momentum_12_1": -1.0, "rate_of_change": scaled + 1.0}


def _strong_long() -> dict:
    return {"momentum_12_1": 1.0, "rate_of_change": 1.0, "trend_strength": 1.0}


class TestThresholdBoundaries:
    def test_composite_plus_0_3_is_long(self):
        s = generate_signal(_boundary_factors(0.3000000001))
        assert s.direction == "LONG"
        assert s.composite == pytest.approx(0.3, abs=1e-7)

    def test_composite_0_299_is_flat(self):
        s = generate_signal(_boundary_factors(0.2999999999))
        assert s.direction == "FLAT"

    def test_composite_minus_0_3_is_short(self):
        s = generate_signal(_short_factors(-0.3000000001))
        assert s.direction == "SHORT"
        assert s.composite == pytest.approx(-0.3, abs=1e-7)

    def test_default_threshold_matches_config_default(self):
        assert DEFAULT_ENTRY_THRESHOLD == 0.3
        assert generate_signal(_boundary_factors(0.3000000001)).direction == "LONG"


class TestInsufficiency:
    def test_empty_factors_flat(self):
        s = generate_signal({})
        assert s.direction == "FLAT"
        assert s.composite == 0.0
        assert s.strength == 0.0
        assert s.fake_breakout_warning is False

    def test_missing_momentum_keys_flat(self):
        s = generate_signal({"atr": 100.0, "volume_ratio": 1.2})
        assert s.direction == "FLAT"
        assert s.composite == 0.0


class TestFakeBreakout:
    def test_fake_breakout_warning_degrades_to_flat(self):
        factors = _strong_long()
        factors["fake_breakout_warning"] = 1.0
        s = generate_signal(factors)
        assert s.direction == "FLAT"
        assert s.fake_breakout_warning is True

    def test_fake_breakout_zero_still_signals(self):
        factors = _strong_long()
        factors["fake_breakout_warning"] = 0.0
        assert generate_signal(factors).direction == "LONG"

    def test_fake_breakout_absent_still_signals(self):
        assert generate_signal(_strong_long()).direction == "LONG"


class TestDirections:
    def test_strong_long(self):
        s = generate_signal(_strong_long())
        assert s.direction == "LONG"
        assert s.strength == pytest.approx(s.composite)
        assert s.strength == pytest.approx(momentum_tanh_score([1.0, 1.0, 1.0]))

    def test_strong_short(self):
        s = generate_signal({"momentum_12_1": -1.0, "rate_of_change": -1.0, "trend_strength": -1.0})
        assert s.direction == "SHORT"

    def test_strength_is_abs_composite(self):
        s = generate_signal(_strong_long())
        assert s.strength == pytest.approx(abs(s.composite))

    def test_reason_includes_composite(self):
        s = generate_signal(_strong_long())
        assert "composite" in s.reason


class TestMomentumTanhScore:
    def test_empty_returns_zero(self):
        assert momentum_tanh_score([]) == 0.0

    def test_single_value_tanh_one(self):
        assert momentum_tanh_score([1.0]) == pytest.approx(math.tanh(1.0))

    def test_all_equal_positives(self):
        assert momentum_tanh_score([0.5, 0.5, 0.5]) == pytest.approx(math.tanh(1.0))

    def test_none_values_filtered(self):
        assert momentum_tanh_score([None, 1.0, 1.0]) == pytest.approx(math.tanh(1.0))


class TestCustomThreshold:
    def test_higher_threshold_blocks(self):
        assert generate_signal(_strong_long(), threshold=0.99).direction == "FLAT"

    def test_lower_threshold_allows(self):
        assert generate_signal(_boundary_factors(0.25), threshold=0.2).direction == "LONG"


class TestRuleSignalType:
    def test_dataclass_shape(self):
        s = generate_signal(_strong_long())
        assert isinstance(s, RuleSignal)
        assert set(s.__dataclass_fields__.keys()) == {
            "direction", "strength", "composite", "fake_breakout_warning", "reason",
        }