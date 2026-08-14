"""
Tests for backtest validation methods: Monte Carlo, Walk Forward, Bootstrap.
"""
import pytest
from datetime import datetime, timezone

from vibe_trading.backtest.validation import (
    BacktestValidator,
    MonteCarloResult,
    WalkForwardResult,
    BootstrapResult
)
from vibe_trading.backtest.models import Trade, BacktestResult


def make_sample_trades(n: int = 10, win_rate: float = 0.6) -> list[Trade]:
    """Generate sample trades for testing."""
    trades = []
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    for i in range(n):
        is_win = (i / n) < win_rate
        entry_price = 10000.0
        exit_price = 10100.0 if is_win else 9950.0
        position_size = 0.01
        pnl = (exit_price - entry_price) * position_size
        pnl_pct = (exit_price - entry_price) / entry_price
        
        trades.append(Trade(
            entry_time=base_time,
            exit_time=base_time,
            side="LONG",
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=position_size,
            pnl=pnl,
            pnl_pct=pnl_pct,
            bars_held=1
        ))
    
    return trades


class TestMonteCarlo:
    """Test Monte Carlo simulation."""
    
    def test_monte_carlo_basic(self):
        """Test basic Monte Carlo simulation."""
        validator = BacktestValidator(seed=42)
        trades = make_sample_trades(10, win_rate=0.6)
        
        result = validator.monte_carlo(trades, num_simulations=100)
        
        assert isinstance(result, MonteCarloResult)
        assert result.num_simulations == 100
        assert len(result.simulated_pnls) == 100
        assert result.original_pnl == sum(t.pnl for t in trades)
        assert result.min_pnl <= result.mean_pnl <= result.max_pnl
        assert result.percentile_5 <= result.percentile_95
    
    def test_monte_carlo_empty_trades(self):
        """Test Monte Carlo with empty trades list."""
        validator = BacktestValidator(seed=42)
        result = validator.monte_carlo([], num_simulations=100)
        
        assert result.num_simulations == 0
        assert result.mean_pnl == 0.0
        assert len(result.simulated_pnls) == 0
    
    def test_monte_carlo_reproducible(self):
        """Test that Monte Carlo is reproducible with same seed."""
        trades = make_sample_trades(10)
        
        validator1 = BacktestValidator(seed=42)
        result1 = validator1.monte_carlo(trades, num_simulations=50)
        
        validator2 = BacktestValidator(seed=42)
        result2 = validator2.monte_carlo(trades, num_simulations=50)
        
        assert result1.simulated_pnls == result2.simulated_pnls


class TestWalkForward:
    """Test Walk Forward analysis."""
    
    def test_walk_forward_basic(self):
        """Test basic Walk Forward analysis."""
        validator = BacktestValidator(seed=42)
        
        # Generate sample klines
        klines = []
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(100):
            klines.append({
                "open_time": int((base_time.timestamp() + i * 3600) * 1000),
                "open": 10000.0 + i * 10,
                "high": 10050.0 + i * 10,
                "low": 9950.0 + i * 10,
                "close": 10020.0 + i * 10,
                "volume": 1000.0,
                "close_time": int((base_time.timestamp() + (i + 1) * 3600) * 1000),
            })
        
        # Mock backtest runner
        def mock_run_backtest(kl):
            return BacktestResult(
                symbol="BTCUSDT",
                interval="1h",
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                initial_balance=10000.0,
                final_balance=10500.0,
                total_pnl=500.0,
                total_pnl_pct=0.05,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=0.6,
                avg_pnl=100.0,
                avg_win=150.0,
                avg_loss=-50.0,
                max_drawdown=200.0,
                max_drawdown_pct=0.02,
                sharpe_ratio=1.5,
                trades=[]
            )
        
        result = validator.walk_forward(
            klines,
            run_backtest=mock_run_backtest,
            in_sample_pct=0.7,
            num_windows=5
        )
        
        assert isinstance(result, WalkForwardResult)
        assert result.num_windows == 5
        assert len(result.window_results) == 5
        assert 0.0 <= result.efficiency_ratio <= 1.0
    
    def test_walk_forward_insufficient_data(self):
        """Test Walk Forward with insufficient data."""
        validator = BacktestValidator(seed=42)
        klines = [{"open_time": i, "close": 100.0} for i in range(5)]
        
        def mock_run(kl):
            return BacktestResult(
                symbol="BTCUSDT",
                interval="1h",
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                initial_balance=10000.0,
                final_balance=10000.0,
                total_pnl=0.0,
                total_pnl_pct=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                avg_pnl=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                max_drawdown=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                trades=[]
            )
        
        result = validator.walk_forward(
            klines,
            run_backtest=mock_run,
            in_sample_pct=0.7,
            num_windows=5
        )
        
        assert result.num_windows == 0
        assert result.efficiency_ratio == 0.0


class TestBootstrap:
    """Test Bootstrap confidence intervals."""
    
    def test_bootstrap_basic(self):
        """Test basic Bootstrap confidence interval."""
        validator = BacktestValidator(seed=42)
        trades = make_sample_trades(20, win_rate=0.6)
        
        result = validator.bootstrap(trades, num_resamples=100)
        
        assert isinstance(result, BootstrapResult)
        assert result.num_resamples == 100
        assert len(result.bootstrap_stats) == 100
        assert result.original_stat is not None
        assert result.ci_lower <= result.ci_upper
    
    def test_bootstrap_empty_trades(self):
        """Test Bootstrap with empty trades list."""
        validator = BacktestValidator(seed=42)
        result = validator.bootstrap([], num_resamples=100)
        
        assert result.num_resamples == 0
        assert result.original_stat == 0.0
        assert len(result.bootstrap_stats) == 0
    
    def test_bootstrap_reproducible(self):
        """Test that Bootstrap is reproducible with same seed."""
        trades = make_sample_trades(10)
        
        validator1 = BacktestValidator(seed=42)
        result1 = validator1.bootstrap(trades, num_resamples=50)
        
        validator2 = BacktestValidator(seed=42)
        result2 = validator2.bootstrap(trades, num_resamples=50)
        
        assert result1.bootstrap_stats == result2.bootstrap_stats
