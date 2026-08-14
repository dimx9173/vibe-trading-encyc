"""
Alpha Factors Module

Provides alpha factor calculations for both live trading and backtest.
Includes 23 pre-configured factors across momentum, volatility, volume, and mean reversion categories.
"""

from .zoo import AlphaZoo

__all__ = [
    "AlphaZoo",
]
