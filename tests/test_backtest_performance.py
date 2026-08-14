"""
Performance regression tests for backtest engine optimization.
TDD Red phase: these tests should FAIL before optimization.
"""
import pytest
import time
from datetime import datetime, timezone

from vibe_trading.backtest.engine import BacktestEngine
from vibe_trading.backtest.models import BacktestConfig


def make_klines(n: int, start_price: float = 100.0, drift: float = 0.1, seed: int = 42):
    """Generate synthetic klines for benchmarking."""
    import random
    rng = random.Random(seed)
    klines = []
    price = start_price
    base_ms = 1_700_000_000_000
    for i in range(n):
        price += drift + rng.uniform(-0.2, 0.2)
        klines.append({
            "open_time_ms": base_ms + i * 60_000,
            "open": price - 0.1,
            "high": price + 0.3,
            "low": price - 0.3,
            "close": price,
            "volume": 1000.0,
        })
    return klines


@pytest.fixture
def config():
    return BacktestConfig(
        symbol="BTCUSDT",
        interval="1h",
        start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2024, 12, 31, tzinfo=timezone.utc),
        initial_balance=10_000.0,
    )


@pytest.fixture
def engine(config):
    return BacktestEngine(config)


class TestPerformanceTargets:
    """Performance regression tests — should FAIL before optimization, PASS after."""

    def test_single_backtest_10k_bars_under_50ms(self, engine):
        """Target: single backtest with 10k bars completes in < 50ms."""
        klines = make_klines(10_000)
        # Warm up
        engine.run(klines, fast_period=10, slow_period=30)
        # Measure
        start = time.perf_counter()
        result = engine.run(klines, fast_period=10, slow_period=30)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert result.total_trades > 0  # Sanity check
        assert elapsed_ms < 50, f"Expected < 50ms, got {elapsed_ms:.2f}ms"

    def test_grid_search_20_params_10k_bars_under_500ms(self, engine):
        """Target: 20 parameter combinations × 10k bars completes in < 500ms."""
        klines = make_klines(10_000)
        params = [(5, 20), (5, 30), (5, 50),
                  (10, 20), (10, 30), (10, 50),
                  (15, 30), (15, 50), (15, 80),
                  (20, 40), (20, 60), (20, 100),
                  (30, 60), (30, 90), (30, 120),
                  (40, 80), (40, 120), (50, 100),
                  (50, 150), (60, 120)]
        # Warm up
        for fast, slow in params[:3]:
            engine.run(klines, fast_period=fast, slow_period=slow)
        # Measure
        start = time.perf_counter()
        for fast, slow in params:
            engine.run(klines, fast_period=fast, slow_period=slow)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Expected < 500ms for 20 params, got {elapsed_ms:.2f}ms"

    def test_100k_bars_under_200ms(self, engine):
        """Target: 100k bars single backtest completes in < 200ms."""
        klines = make_klines(100_000)
        # Warm up
        engine.run(klines, fast_period=10, slow_period=30)
        # Measure
        start = time.perf_counter()
        result = engine.run(klines, fast_period=10, slow_period=30)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert result.total_trades > 0
        assert elapsed_ms < 200, f"Expected < 200ms for 100k bars, got {elapsed_ms:.2f}ms"
