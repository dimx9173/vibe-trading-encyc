"""L1: Exit Ladder 三級階梯測試 (規格書 §2.1)."""
import pytest

from vibe_trading.execution.exit_ladder import (
    ExitLadderConfig, ExitLadderEngine, LadderStage,
)


@pytest.fixture
def engine():
    return ExitLadderEngine()


class TestLadderStages:
    def test_tp1_hit(self, engine):
        # LONG entry=100, atr=2 → R=3, TP1=104.5
        stage, ratio, sl, _ = engine.evaluate_position(
            "LONG", 100, 105, LadderStage.INITIAL, 105, 95, 2.0)
        assert stage == LadderStage.TP1_HIT_30
        assert ratio == 0.30
        assert sl == 100  # 保本

    def test_tp2_hit(self, engine):
        stage, ratio, sl, _ = engine.evaluate_position(
            "LONG", 100, 108, LadderStage.TP1_HIT_30, 108, 95, 2.0)
        assert stage == LadderStage.TP2_HIT_40
        assert ratio == 0.40

    def test_trailing_close(self, engine):
        stage, ratio, _, _ = engine.evaluate_position(
            "LONG", 100, 104, LadderStage.TP2_HIT_40, 108, 95, 2.0)
        assert stage == LadderStage.CLOSED
        assert ratio == 0.30

    def test_short_direction(self, engine):
        # SHORT entry=100, price 下跌 95 → 盈利 5 ≥ 4.5 (TP1)
        stage, ratio, sl, _ = engine.evaluate_position(
            "SHORT", 100, 95, LadderStage.INITIAL, 100, 94, 2.0)
        assert stage == LadderStage.TP1_HIT_30

    def test_waiting_tp1(self, engine):
        stage, ratio, sl, _ = engine.evaluate_position(
            "LONG", 100, 102, LadderStage.INITIAL, 102, 95, 2.0)
        assert stage == LadderStage.INITIAL and ratio == 0.0


class TestExhaustion:
    def test_early_exit(self, engine):
        stage, ratio, _, _ = engine.evaluate_position(
            "LONG", 100, 106, LadderStage.INITIAL, 106, 95, 2.0,
            is_exhausted=True)
        assert stage == LadderStage.EXHAUSTION_EARLY_EXIT
        assert ratio == 0.50

    def test_volume_check_trigger(self, engine):
        vols = [100.0] * 21 + [200.0]
        prices = [100.0, 100.1, 100.2]
        assert engine.check_volume_exhaustion(vols, prices, 2.0, 2.0) is True

    def test_volume_check_no_stagnation(self, engine):
        vols = [100.0] * 21 + [200.0]
        prices = [100.0, 101.0, 102.0]  # 2% 變動
        assert engine.check_volume_exhaustion(vols, prices, 2.0, 2.0) is False

    def test_volume_check_low_gain(self, engine):
        vols = [100.0] * 21 + [200.0]
        prices = [100.0, 100.1, 100.2]
        assert engine.check_volume_exhaustion(vols, prices, 0.5, 2.0) is False
