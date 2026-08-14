"""
Null Sentiment Plugin

Empty implementation used for:
- Backtest mode (no sentiment data available)
- Fallback when real plugins are unavailable
- Testing purposes

Always returns None for sentiment, indicating data is unavailable.
"""
from typing import Optional
from .base import SentimentPlugin


class NullSentiment(SentimentPlugin):
    """Null sentiment plugin (no-op implementation)"""
    
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """Always returns None - no sentiment data available"""
        return None
    
    @property
    def is_available(self) -> bool:
        """Always returns False - plugin is not available"""
        return False
