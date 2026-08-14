"""
Liquidation Plugin Interface

Defines the abstract interface for liquidation data plugins.
Supports both real-time WebSocket feeds and REST API queries.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime


class LiquidationData(BaseModel):
    """Standardized liquidation data model"""
    symbol: str
    side: str  # "long" or "short"
    price: float
    quantity: float
    usd_value: float
    exchange: str
    timestamp: datetime


class LiquidationPlugin(ABC):
    """Liquidation plugin interface"""
    
    @abstractmethod
    async def fetch(self, symbol: str, **kwargs) -> Optional[List[LiquidationData]]:
        """
        Fetch liquidation data for symbol
        
        Returns:
            List of liquidation events, or None if unavailable
        """
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if plugin is available"""
        pass
    
    @property
    def name(self) -> str:
        """Get plugin name"""
        return self.__class__.__name__
