"""
Unified Data Source - Abstract Interface

Defines the core interface for both live trading and backtest systems.
Ensures consistency between real-time and historical data access.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime


class DataResult(BaseModel):
    """Unified data result"""
    source: str
    symbol: str
    data: Any
    timestamp: datetime
    freshness_score: float  # 0-1
    confidence: float       # 0-1


class Kline(BaseModel):
    """K-line data model"""
    symbol: str
    interval: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: Optional[datetime] = None


class UnifiedDataSource(ABC):
    """Unified data source (live + backtest)"""
    
    @abstractmethod
    async def get_klines(
        self, 
        symbol: str, 
        interval: str,
        start: Optional[datetime] = None,  # For backtest
        end: Optional[datetime] = None,     # For backtest
        limit: Optional[int] = None         # For live
    ) -> List[Kline]:
        """Get K-line data"""
        pass
    
    async def get_technical_indicators(
        self,
        symbol: str,
        interval: str,
        **kwargs
    ) -> Dict[str, float]:
        """Calculate technical indicators (shared between live and backtest)"""
        klines = await self.get_klines(symbol, interval, **kwargs)
        # Import here to avoid circular dependency
        from .indicators.technical import TechnicalAnalyzer
        return TechnicalAnalyzer.calculate(klines)
    
    async def get_alpha_factors(
        self,
        symbol: str,
        interval: str,
        **kwargs
    ) -> Dict[str, float]:
        """Calculate Alpha factors (shared between live and backtest)"""
        klines = await self.get_klines(symbol, interval, **kwargs)
        # Import here to avoid circular dependency
        from .alphas.zoo import AlphaZoo
        return AlphaZoo.calculate(klines)
