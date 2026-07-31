"""
Tests for the backtest engine (Phase 1 minimal implementation).

The engine was a stub: 11 lines, no `run()`, no P&L math. These tests pin the
new behavior so we can iterate on real P&L numbers instead of guesses.
"""
from datetime import datetime, timezone

import pytest

from vibe_trading.backtest.engine import BacktestEngine
from vibe_trading.backtest.models import BacktestConfig, BacktestResult, Trade


# === Fixtures ===

def make_trending_klines(n: int = 200, start_price: float = 100.0, drift: float = 0.5, seed: int = 42):
    """Generate a clear uptrending K-line series (drift per bar > 0)."""
    import random
    rng = random.Random(seed)
    klines = []
    price = start_price
    base_ms = 1_700_000_000_000
    for i in range(n):
        price += drift + rng.uniform(-0.3, 0.3)
        klines.append({
            "open_time_ms": base_ms + i * 60_000,
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000.0,
        })
    return klines


def make_oscillating_klines(n: int = 200, start_price: float = 100.0, amp: float = 5.0, period: int = 30, seed: int = 7):
    """Generate a sine-wave K-line series (cycles between up and down)."""
    import math
    import random
    rng = random.Random(seed)
    klines = []
    price = start_price
    base_ms = 1_700_000_000_000
    for i in range(n):
        target = start_price + amp * math.sin(2 * math.pi * i / period)
        price = target + rng.uniform(-0.2, 0.2)
        klines.append({
            "open_time_ms": base_ms + i * 60_000,
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000.0,
        })
    return klines


def make_flat_klines(n: int = 200, start_price: float = 100.0, seed: int = 1):
    """Generate a perfectly flat K-line series (constant price, no MA crossover)."""
    klines = []
    base_ms = 1_700_000_000_000
    for i in range(n):
        # Constant price: fast MA == slow MA == start_price for every bar,
        # so the crossover check (fast > slow) is never true.
        klines.append({
            "open_time_ms": base_ms + i * 60_000,
            "open": start_price,
            "high": start_price,
            "low": start_price,
            "close": start_price,
            "volume": 1000.0,
        })
    return klines


@pytest.fixture
def config():
    return BacktestConfig(
        symbol="BTCUSDT",
        interval="30m",
        start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        initial_balance=10_000.0,
    )


@pytest.fixture
def engine(config):
    return BacktestEngine(config)


# === Validation ===

class TestValidation:
    def test_empty_klines_returns_zero_stats(self, engine):
        result = engine.run([])
        assert result.total_trades == 0
        assert result.final_balance == engine.config.initial_balance
        assert result.total_pnl == 0.0

    def test_invalid_fast_period_zero(self, engine):
        with pytest.raises(ValueError, match="positive"):
            engine.run(make_trending_klines(50), fast_period=0)

    def test_invalid_slow_period_zero(self, engine):
        with pytest.raises(ValueError, match="positive"):
            engine.run(make_trending_klines(50), slow_period=0)

    def test_fast_must_be_less_than_slow(self, engine):
        with pytest.raises(ValueError, match="fast_period must be"):
            engine.run(make_trending_klines(50), fast_period=30, slow_period=10)

    def test_invalid_position_pct(self, engine):
        with pytest.raises(ValueError, match="position_pct"):
            engine.run(make_trending_klines(50), position_pct=0.0)
        with pytest.raises(ValueError, match="position_pct"):
            engine.run(make_trending_klines(50), position_pct=1.5)


# === Trending market: should produce trades & profit ===

class TestTrendingMarket:
    def test_produces_long_entries(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        # Clear uptrend should trigger at least one LONG entry
        assert result.total_trades >= 1
        # All trades are LONG (long-only strategy)
        assert all(t.side == "LONG" for t in result.trades)
        assert result.winning_trades + result.losing_trades == result.total_trades

    def test_uptrend_is_profitable(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        # Sum of all P&L should be positive in a clear uptrend
        assert result.total_pnl > 0
        assert result.final_balance > engine.config.initial_balance

    def test_pnl_consistent_with_trades(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        computed_total = sum(t.pnl for t in result.trades)
        assert abs(result.total_pnl - computed_total) < 1e-6
        computed_final = engine.config.initial_balance + computed_total
        assert abs(result.final_balance - computed_final) < 1e-6


# === Oscillating market: should trade both wins and losses ===

class TestOscillatingMarket:
    def test_oscillating_produces_round_trips(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        # 600 bars / 30-bar period = 20 cycles → many trades
        assert result.total_trades >= 5

    def test_oscillating_win_rate_in_range(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        # Oscillating markets don't always win — win rate is 0..1
        assert 0.0 <= result.win_rate <= 1.0
        # Avg win should be positive, avg loss should be negative
        if result.winning_trades > 0:
            assert result.avg_win > 0
        if result.losing_trades > 0:
            assert result.avg_loss < 0


# === Flat market: minimal or no trades ===

class TestFlatMarket:
    def test_flat_market_no_trades(self, engine):
        klines = make_flat_klines(n=200)
        result = engine.run(klines, fast_period=10, slow_period=30)
        # No clear trend → no MA crossover → no trades
        assert result.total_trades == 0
        assert result.final_balance == engine.config.initial_balance


# === Statistics correctness ===

class TestStatsCorrectness:
    def test_winning_losing_counts(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        wins = sum(1 for t in result.trades if t.pnl > 0)
        losses = sum(1 for t in result.trades if t.pnl <= 0)
        assert result.winning_trades == wins
        assert result.losing_trades == losses
        assert result.winning_trades + result.losing_trades == result.total_trades

    def test_win_rate(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        if result.total_trades > 0:
            expected_wr = result.winning_trades / result.total_trades
            assert abs(result.win_rate - expected_wr) < 1e-6

    def test_max_drawdown_non_negative(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        assert result.max_drawdown >= 0
        assert result.max_drawdown_pct >= 0
        assert result.max_drawdown_pct <= 1.0

    def test_drawdown_tracks_equity_curve(self, engine):
        # Manually reconstruct the equity curve and verify max drawdown
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        equity = engine.config.initial_balance
        peak = engine.config.initial_balance
        max_dd = 0.0
        for t in result.trades:
            equity += t.pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        assert abs(result.max_drawdown - max_dd) < 1e-6

    def test_sharpe_with_many_trades(self, engine):
        klines = make_oscillating_klines(n=600, amp=5.0, period=30)
        result = engine.run(klines, fast_period=5, slow_period=15)
        # Sharpe should be a finite number when there's variance
        if result.total_trades > 1:
            assert -10.0 <= result.sharpe_ratio <= 10.0


# === Trade record fields ===

class TestTradeFields:
    def test_trade_has_required_fields(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        assert result.total_trades >= 1
        t = result.trades[0]
        assert isinstance(t, Trade)
        assert t.entry_time.tzinfo is not None
        assert t.exit_time.tzinfo is not None
        assert t.entry_time < t.exit_time
        assert t.entry_price > 0
        assert t.exit_price > 0
        assert t.position_size > 0
        assert t.bars_held >= 1

    def test_long_trade_pnl_matches_prices(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        for t in result.trades:
            expected_pnl = (t.exit_price - t.entry_price) * t.position_size
            assert abs(t.pnl - expected_pnl) < 1e-6


# === BacktestResult shape ===

class TestResultShape:
    def test_result_has_all_fields(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        assert isinstance(result, BacktestResult)
        assert result.symbol == "BTCUSDT"
        assert result.interval == "30m"
        assert result.initial_balance == 10_000.0
        assert result.start_time.tzinfo is not None
        assert result.end_time.tzinfo is not None
        assert result.start_time < result.end_time

    def test_summary_is_non_empty_string(self, engine):
        klines = make_trending_klines(n=200, drift=0.5)
        result = engine.run(klines, fast_period=10, slow_period=30)
        summary = result.summary()
        assert isinstance(summary, str)
        assert "BTCUSDT" in summary
        assert "Win rate" in summary
        assert "Total P&L" in summary
        assert "Sharpe" in summary
        assert "Max drawdown" in summary


# === Smoke test: end-to-end CLI-style usage ===

class TestSmokeUsage:
    def test_synthetic_ohlcv_runs_successfully(self, engine):
        """The exact pattern the user would run from a Python REPL."""
        klines = make_trending_klines(n=120, drift=0.3)
        result = engine.run(klines)
        # Acceptable that any reasonable MA crossover produced *some* trades
        # or none — the test is that it doesn't crash and the result is well-formed.
        assert isinstance(result, BacktestResult)
        assert result.initial_balance > 0
        assert result.final_balance > 0
