"""
Backtest validation methods: Monte Carlo, Walk Forward, Bootstrap.

These methods assess strategy robustness beyond simple backtest results.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Dict, Any, Callable

from .models import BacktestResult, Trade


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""
    original_pnl: float
    mean_pnl: float
    std_pnl: float
    min_pnl: float
    max_pnl: float
    percentile_5: float
    percentile_95: float
    num_simulations: int
    simulated_pnls: List[float]


@dataclass
class WalkForwardResult:
    """Walk Forward analysis result."""
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    efficiency_ratio: float  # OOS / IS Sharpe
    num_windows: int
    window_results: List[Dict[str, float]]


@dataclass
class BootstrapResult:
    """Bootstrap confidence interval result."""
    original_stat: float
    mean_stat: float
    std_stat: float
    ci_lower: float  # 2.5th percentile
    ci_upper: float  # 97.5th percentile
    num_resamples: int
    bootstrap_stats: List[float]


class BacktestValidator:
    """Statistical validation for backtest results."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)

    def monte_carlo(
        self,
        trades: List[Trade],
        num_simulations: int = 1000,
        perturbation_pct: float = 0.1
    ) -> MonteCarloResult:
        """
        Monte Carlo simulation: randomly perturb trade returns to assess robustness.

        Args:
            trades: Original trades from backtest
            num_simulations: Number of Monte Carlo iterations
            perturbation_pct: Max random perturbation (±10% by default)

        Returns:
            MonteCarloResult with statistical distribution of PnL
        """
        if not trades:
            return MonteCarloResult(
                original_pnl=0.0,
                mean_pnl=0.0,
                std_pnl=0.0,
                min_pnl=0.0,
                max_pnl=0.0,
                percentile_5=0.0,
                percentile_95=0.0,
                num_simulations=0,
                simulated_pnls=[]
            )

        original_pnl = sum(t.pnl for t in trades)
        simulated_pnls = []

        for _ in range(num_simulations):
            # Perturb each trade's PnL by random factor
            simulated_pnl = 0.0
            for trade in trades:
                # Random perturbation: uniform [1-pct, 1+pct]
                factor = 1.0 + random.uniform(-perturbation_pct, perturbation_pct)
                simulated_pnl += trade.pnl * factor
            simulated_pnls.append(simulated_pnl)

        simulated_pnls.sort()
        mean_pnl = sum(simulated_pnls) / len(simulated_pnls)
        variance = sum((x - mean_pnl) ** 2 for x in simulated_pnls) / len(simulated_pnls)
        std_pnl = variance ** 0.5

        # Percentiles
        idx_5 = int(0.05 * len(simulated_pnls))
        idx_95 = int(0.95 * len(simulated_pnls))

        return MonteCarloResult(
            original_pnl=original_pnl,
            mean_pnl=mean_pnl,
            std_pnl=std_pnl,
            min_pnl=min(simulated_pnls),
            max_pnl=max(simulated_pnls),
            percentile_5=simulated_pnls[idx_5],
            percentile_95=simulated_pnls[idx_95],
            num_simulations=num_simulations,
            simulated_pnls=simulated_pnls
        )

    def walk_forward(
        self,
        klines: List[Dict[str, Any]],
        run_backtest: Callable[[List[Dict[str, Any]]], BacktestResult],
        in_sample_pct: float = 0.7,
        num_windows: int = 5
    ) -> WalkForwardResult:
        """
        Walk Forward analysis: test strategy on rolling windows.

        Splits data into rolling in-sample (training) and out-of-sample (testing)
        windows to assess if strategy performance degrades on unseen data.

        Args:
            klines: Full K-line dataset
            run_backtest: Function to run backtest on a subset of klines
            in_sample_pct: Percentage of each window for in-sample (default 70%)
            num_windows: Number of rolling windows (default 5)

        Returns:
            WalkForwardResult with IS/OOS Sharpe comparison
        """
        if len(klines) < num_windows * 2:
            return WalkForwardResult(
                in_sample_sharpe=0.0,
                out_of_sample_sharpe=0.0,
                efficiency_ratio=0.0,
                num_windows=0,
                window_results=[]
            )

        window_size = len(klines) // num_windows
        is_sharpes = []
        oos_sharpes = []
        window_results = []

        for i in range(num_windows):
            start_idx = i * window_size
            end_idx = min(start_idx + window_size, len(klines))
            window_klines = klines[start_idx:end_idx]

            # Split into in-sample and out-of-sample
            is_size = int(len(window_klines) * in_sample_pct)
            is_klines = window_klines[:is_size]
            oos_klines = window_klines[is_size:]

            # Run backtest on in-sample
            is_result = run_backtest(is_klines)
            is_sharpes.append(is_result.sharpe_ratio)

            # Run backtest on out-of-sample
            oos_result = run_backtest(oos_klines)
            oos_sharpes.append(oos_result.sharpe_ratio)

            window_results.append({
                "window": i + 1,
                "is_sharpe": is_result.sharpe_ratio,
                "oos_sharpe": oos_result.sharpe_ratio,
                "is_trades": is_result.total_trades,
                "oos_trades": oos_result.total_trades
            })

        avg_is_sharpe = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0.0
        avg_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
        efficiency = avg_oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0.0

        return WalkForwardResult(
            in_sample_sharpe=avg_is_sharpe,
            out_of_sample_sharpe=avg_oos_sharpe,
            efficiency_ratio=efficiency,
            num_windows=num_windows,
            window_results=window_results
        )

    def bootstrap(
        self,
        trades: List[Trade],
        num_resamples: int = 1000,
        statistic: str = "mean_pnl"
    ) -> BootstrapResult:
        """
        Bootstrap confidence interval for trade statistics.

        Resamples trades with replacement to estimate confidence intervals
        for statistics like mean PnL, Sharpe ratio, etc.

        Args:
            trades: Original trades from backtest
            num_resamples: Number of bootstrap resamples (default 1000)
            statistic: Which statistic to compute ("mean_pnl", "sharpe", "win_rate")

        Returns:
            BootstrapResult with confidence intervals
        """
        if not trades:
            return BootstrapResult(
                original_stat=0.0,
                mean_stat=0.0,
                std_stat=0.0,
                ci_lower=0.0,
                ci_upper=0.0,
                num_resamples=0,
                bootstrap_stats=[]
            )

        def compute_stat(trade_list: List[Trade]) -> float:
            if statistic == "mean_pnl":
                return sum(t.pnl for t in trade_list) / len(trade_list)
            elif statistic == "sharpe":
                if len(trade_list) < 2:
                    return 0.0
                mean_pnl = sum(t.pnl_pct for t in trade_list) / len(trade_list)
                variance = sum((t.pnl_pct - mean_pnl) ** 2 for t in trade_list) / len(trade_list)
                std = variance ** 0.5
                return mean_pnl / std if std > 0 else 0.0
            elif statistic == "win_rate":
                wins = sum(1 for t in trade_list if t.pnl > 0)
                return wins / len(trade_list)
            else:
                raise ValueError(f"Unknown statistic: {statistic}")

        original_stat = compute_stat(trades)
        bootstrap_stats = []

        for _ in range(num_resamples):
            # Resample with replacement
            resampled = random.choices(trades, k=len(trades))
            bootstrap_stats.append(compute_stat(resampled))

        bootstrap_stats.sort()
        mean_stat = sum(bootstrap_stats) / len(bootstrap_stats)
        variance = sum((x - mean_stat) ** 2 for x in bootstrap_stats) / len(bootstrap_stats)
        std_stat = variance ** 0.5

        # 95% confidence interval (2.5th and 97.5th percentiles)
        idx_lower = int(0.025 * len(bootstrap_stats))
        idx_upper = int(0.975 * len(bootstrap_stats))

        return BootstrapResult(
            original_stat=original_stat,
            mean_stat=mean_stat,
            std_stat=std_stat,
            ci_lower=bootstrap_stats[idx_lower],
            ci_upper=bootstrap_stats[idx_upper],
            num_resamples=num_resamples,
            bootstrap_stats=bootstrap_stats
        )
