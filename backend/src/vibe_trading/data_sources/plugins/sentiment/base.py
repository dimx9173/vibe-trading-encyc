"""
Sentiment Plugin Interface

Defines the abstract interface for sentiment analysis plugins.
Plugins can be enabled/disabled via configuration.
"""
from abc import ABC, abstractmethod
from typing import Optional


class SentimentPlugin(ABC):
    """Sentiment plugin interface"""
    
    @abstractmethod
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """
        Get sentiment score for symbol
        
        Returns:
            float: Sentiment score from -1.0 (very negative) to +1.0 (very positive)
                   None if data is unavailable
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
