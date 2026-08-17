"""L1: DSR 檢驗測試 (規格書 §2.6)."""
from vibe_trading.quant.deflated_sharpe import (
    deflated_sharpe_ratio, expected_max_sharpe, sharpe_ratio,
)


class TestSharpe:
    def test_positive(self):
        sr = sharpe_ratio([0.01] * 10 + [0.02] * 10)
        assert sr > 0

    def test_zero_variance(self):
        assert sharpe_ratio([0.01] * 5) == 0.0


class TestExpectedMaxSharpe:
    def test_single_trial(self):
        # K=1 → SR0 應接近 0 (無多重檢驗懲罰)
        assert expected_max_sharpe(1) < 0.5

    def test_many_trials_penalty(self):
        assert expected_max_sharpe(100) > expected_max_sharpe(1)


class TestDSR:
    def test_significant_alpha(self):
        rets = [0.01, 0.02, 0.015, 0.03, 0.01, 0.025, 0.02, 0.04, 0.01, 0.015]
        d = deflated_sharpe_ratio(rets, num_trials=1)
        assert d["significant"] is True
        assert d["dsr"] >= 0.95

    def test_insignificant(self):
        rets = [0.001, -0.002, 0.003, -0.001, 0.002, -0.003, 0.001]
        d = deflated_sharpe_ratio(rets, num_trials=10)
        assert d["significant"] is False

    def test_insufficient_data(self):
        d = deflated_sharpe_ratio([0.01, 0.02], num_trials=1)
        assert d["significant"] is False
