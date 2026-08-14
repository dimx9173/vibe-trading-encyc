"""
Technical Indicators Module

Provides technical indicator calculations for both live trading and backtest.
All indicators work with standardized K-line data.
"""

from .technical import TechnicalAnalyzer

__all__ = [
    "TechnicalAnalyzer",
]
