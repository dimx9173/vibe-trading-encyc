"""Task 4 TDD: adaptive BB dual-mode with hysteresis and MR score."""
import math

import pytest

from vibe_trading.rule_engine.signal import generate_signal, mean_reversion_score


def test_choppy_returns_flat_or_mr_flipped_via_config():
    bb_history = [0.03] * 20 + [0.015, 0.015, 0.015]
    factors = {
        "momentum_12_1": 1.0,
        "rate_of_change": 1.0,
        "rsi_zscore": 0.2,
        "bollinger_band_width": 0.015,
        "price_to_ma": 0.01,
    }
    sig = generate_signal(factors, bb_history=bb_history)
    assert sig.direction == "FLAT"
    assert "choppy" in sig.reason.lower()
    assert "median" in sig.reason.lower()
    factors_mr = {
        "momentum_12_1": 0.1,
        "rate_of_change": 0.1,
        "rsi_zscore": -0.8,
        "bollinger_band_width": 0.015,
        "price_to_ma": -0.08,
    }
    sig_mr = generate_signal(factors_mr, bb_history=bb_history, mr_enabled=True)
    assert sig_mr.direction != "FLAT"
    assert sig_mr.composite == pytest.approx(mean_reversion_score(-0.8, -0.08), abs=1e-7)


def test_hysteresis_requires_3_enter_2_exit():
    base = [0.03] * 20
    factors = {
        "momentum_12_1": 1.0,
        "rate_of_change": 1.0,
        "rsi_zscore": 0.2,
        "bollinger_band_width": 0.015,
        "price_to_ma": 0.0,
    }
    h1 = base + [0.015]
    s1 = generate_signal(factors, bb_history=h1)
    assert s1.direction != "FLAT" or "choppy" not in s1.reason.lower()
    h2 = base + [0.015, 0.015]
    s2 = generate_signal(factors, bb_history=h2)
    assert s2.direction != "FLAT" or "choppy" not in s2.reason.lower()
    h3 = base + [0.015, 0.015, 0.015]
    s3 = generate_signal(factors, bb_history=h3)
    assert s3.direction == "FLAT"
    assert "choppy" in s3.reason.lower()
    exit1 = base + [0.015, 0.015, 0.015, 0.03]
    s_exit1 = generate_signal(factors, bb_history=exit1)
    assert s_exit1.direction == "FLAT"
    assert "choppy" in s_exit1.reason.lower()
    exit2 = base + [0.015, 0.015, 0.015, 0.03, 0.03]
    s_exit2 = generate_signal(factors, bb_history=exit2)
    assert s_exit2.direction != "FLAT"
    assert "choppy" not in s_exit2.reason.lower()


def test_adaptive_threshold_scales_with_median():
    factors = {
        "momentum_12_1": 1.0,
        "rate_of_change": 1.0,
        "rsi_zscore": 0.2,
        "bollinger_band_width": 0.03,
        "price_to_ma": 0.0,
    }
    hist_high = [0.05] * 20 + [0.03, 0.03, 0.03]
    s_high = generate_signal(factors, bb_history=hist_high)
    assert s_high.direction == "FLAT"
    assert "choppy" in s_high.reason.lower()
    hist_low = [0.02] * 20 + [0.03, 0.03, 0.03]
    s_low = generate_signal(factors, bb_history=hist_low)
    assert s_low.direction == "LONG"
    assert "choppy" not in s_low.reason.lower()
