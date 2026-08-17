"""L1: Dynamic IC 調權測試 (規格書 §2.5)."""
import pytest

from vibe_trading.quant.factor_ic import (
    DynamicICMonitor, ic_multiplier, spearman_rank_ic,
)


class TestSpearmanIC:
    def test_perfect_positive(self):
        assert abs(spearman_rank_ic([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) - 1.0) < 1e-6

    def test_perfect_negative(self):
        assert abs(spearman_rank_ic([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) + 1.0) < 1e-6

    def test_insufficient(self):
        assert spearman_rank_ic([1, 2], [1, 2]) is None


class TestMultiplier:
    def test_strong(self):
        assert ic_multiplier(0.20)["multiplier"] == 1.5

    def test_normal(self):
        assert ic_multiplier(0.10)["multiplier"] == 1.0

    def test_weak_interpolate(self):
        m = ic_multiplier(0.03)["multiplier"]
        assert 0.3 < m < 1.0

    def test_noise(self):
        assert ic_multiplier(0.01)["multiplier"] == 0.3

    def test_reversal(self):
        assert ic_multiplier(-0.10)["signal"] == "REVERSAL"


class TestMonitor:
    def test_evaluate(self):
        m = DynamicICMonitor(lookback=10, forward=3)
        for i in range(20):
            m.update_price(100 + i)
            m.record_factor("momentum", i * 0.5)
        res = m.evaluate()
        assert "momentum" in res
        assert "rank_ic" in res["momentum"]
        assert 0.0 <= res["momentum"]["multiplier"] <= 1.5

    def test_ema_smoothing(self):
        from vibe_trading.quant.factor_ic import ema_smooth_multiplier
        # α=0.2 平滑: 1.0 → 1.5 需多步, 非跳變
        assert ema_smooth_multiplier(1.0, 1.5) == pytest.approx(1.1)
        assert ema_smooth_multiplier(1.5, 0.3) == pytest.approx(1.26)
