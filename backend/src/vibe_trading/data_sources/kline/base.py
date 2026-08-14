"""
K-line Data Source Interface

Abstract base class for K-line data sources.
Supports both real-time and historical data access.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from ..base import Kline


class KlineDataSource(ABC):
    """K-line data source interface"""
    
    @abstractmethod
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Kline]:
        """
        Get K-line data
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            interval: Time interval (e.g., "30m", "1h")
            start: Start time (for historical/backtest)
            end: End time (for historical/backtest)
            limit: Maximum number of candles (for real-time)
        
        Returns:
            List of Kline objects
        """
        pass
