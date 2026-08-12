"""
Performance metrics for backtest evaluation.

Implements standard quantitative finance metrics:
- Cumulative Return (CR)
- Annualized Return (ARR)
- Sharpe Ratio
- Sortino Ratio
- Maximum Drawdown (MaxDD)
- Win Rate
"""
from __future__ import annotations

import math
from typing import List, Optional


def cumulative_return(equity_curve: List[float]) -> float:
    """
    Calculate cumulative return from equity curve.
    
    Args:
        equity_curve: List of portfolio values over time
    
    Returns:
        Cumulative return as decimal (e.g., 0.5 = 50% return)
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    
    initial = equity_curve[0]
    final = equity_curve[-1]
    
    if initial == 0:
        return 0.0
    
    return (final - initial) / initial


def annualized_return(
    equity_curve: List[float],
    periods_per_year: int = 252
) -> float:
    """
    Calculate annualized return from equity curve.
    
    Args:
        equity_curve: List of portfolio values over time
        periods_per_year: Number of periods per year (252 for daily, 365 for crypto)
    
    Returns:
        Annualized return as decimal
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    
    total_return = cumulative_return(equity_curve)
    num_periods = len(equity_curve) - 1
    
    if num_periods == 0:
        return 0.0
    
    # Annualize: (1 + total_return) ^ (periods_per_year / num_periods) - 1
    annualized = (1 + total_return) ** (periods_per_year / num_periods) - 1
    
    return annualized


def sharpe_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    Calculate Sharpe ratio from returns series.
    
    Sharpe = (Return - Risk-Free Rate) / Std Dev of Returns
    
    Args:
        returns: List of periodic returns (e.g., daily returns)
        risk_free_rate: Annualized risk-free rate (default 0.0)
        periods_per_year: Number of periods per year
    
    Returns:
        Annualized Sharpe ratio
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    # Calculate mean return
    mean_return = sum(returns) / len(returns)
    
    # Calculate standard deviation
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = math.sqrt(variance)
    
    if std_dev == 0:
        return 0.0
    
    # Annualize
    periodic_rf_rate = risk_free_rate / periods_per_year
    sharpe = (mean_return - periodic_rf_rate) / std_dev
    
    # Annualize Sharpe ratio
    annualized_sharpe = sharpe * math.sqrt(periods_per_year)
    
    return annualized_sharpe


def sortino_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    Calculate Sortino ratio from returns series.
    
    Sortino = (Return - Risk-Free Rate) / Downside Deviation
    
    Only considers downside volatility (negative returns).
    
    Args:
        returns: List of periodic returns
        risk_free_rate: Annualized risk-free rate
        periods_per_year: Number of periods per year
    
    Returns:
        Annualized Sortino ratio
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    # Calculate mean return
    mean_return = sum(returns) / len(returns)
    
    # Calculate downside deviation (only negative returns)
    downside_returns = [r for r in returns if r < 0]
    
    if not downside_returns:
        return float('inf') if mean_return > 0 else 0.0
    
    downside_variance = sum(r ** 2 for r in downside_returns) / len(returns)
    downside_deviation = math.sqrt(downside_variance)
    
    if downside_deviation == 0:
        return 0.0
    
    # Annualize
    periodic_rf_rate = risk_free_rate / periods_per_year
    sortino = (mean_return - periodic_rf_rate) / downside_deviation
    
    # Annualize Sortino ratio
    annualized_sortino = sortino * math.sqrt(periods_per_year)
    
    return annualized_sortino


def maximum_drawdown(equity_curve: List[float]) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    MaxDD = (Peak - Trough) / Peak
    
    Args:
        equity_curve: List of portfolio values over time
    
    Returns:
        Maximum drawdown as positive decimal (e.g., 0.2 = 20% drawdown)
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    
    peak = equity_curve[0]
    max_dd = 0.0
    
    for value in equity_curve:
        if value > peak:
            peak = value
        
        if peak > 0:
            drawdown = (peak - value) / peak
            max_dd = max(max_dd, drawdown)
    
    return max_dd


def win_rate(trades: List[dict]) -> float:
    """
    Calculate win rate from trades list.
    
    Args:
        trades: List of trade dictionaries with 'pnl' field
    
    Returns:
        Win rate as decimal (e.g., 0.6 = 60% win rate)
    """
    if not trades:
        return 0.0
    
    winning_trades = sum(1 for t in trades if t.get('pnl', 0) > 0)
    
    return winning_trades / len(trades)


def profit_factor(trades: List[dict]) -> float:
    """
    Calculate profit factor from trades list.
    
    Profit Factor = Gross Profit / Gross Loss
    
    Args:
        trades: List of trade dictionaries with 'pnl' field
    
    Returns:
        Profit factor (higher is better, > 1.0 is profitable)
    """
    if not trades:
        return 0.0
    
    gross_profit = sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0)
    gross_loss = abs(sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def calculate_all_metrics(
    equity_curve: List[float],
    trades: List[dict],
    periods_per_year: int = 365
) -> dict:
    """
    Calculate all performance metrics at once.
    
    Args:
        equity_curve: List of portfolio values over time
        trades: List of trade dictionaries with 'pnl' field
        periods_per_year: Number of periods per year (365 for crypto)
    
    Returns:
        Dictionary with all metrics
    """
    if not equity_curve or len(equity_curve) < 2:
        return {
            'cumulative_return': 0.0,
            'annualized_return': 0.0,
            'sharpe_ratio': 0.0,
            'sortino_ratio': 0.0,
            'maximum_drawdown': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
        }
    
    # Calculate returns from equity curve
    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i-1] > 0:
            ret = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(ret)
    
    return {
        'cumulative_return': cumulative_return(equity_curve),
        'annualized_return': annualized_return(equity_curve, periods_per_year),
        'sharpe_ratio': sharpe_ratio(returns, periods_per_year=periods_per_year),
        'sortino_ratio': sortino_ratio(returns, periods_per_year=periods_per_year),
        'maximum_drawdown': maximum_drawdown(equity_curve),
        'win_rate': win_rate(trades),
        'profit_factor': profit_factor(trades),
    }
