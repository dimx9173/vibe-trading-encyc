"""
RSS Sentiment Plugin

Aggregates news from multiple RSS feeds.
Uses feedparser for RSS parsing.
"""
import feedparser
from typing import Optional, List, Dict
from datetime import datetime
from .base import SentimentPlugin


class RSSSentiment(SentimentPlugin):
    """RSS sentiment aggregator"""
    
    def __init__(self, feed_urls: List[str]):
        self.feed_urls = feed_urls
        self._available = True
    
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """Get sentiment from RSS feeds"""
        try:
            all_items = []
            
            for url in self.feed_urls:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    # Check if entry mentions the symbol
                    if symbol.lower() in entry.get("title", "").lower():
                        all_items.append(entry)
            
            if not all_items:
                return None
            
            # Simple sentiment based on keyword analysis
            positive_keywords = ["bullish", "surge", "rally", "breakout", "gain", "up", "positive"]
            negative_keywords = ["bearish", "crash", "dump", "breakdown", "loss", "down", "negative"]
            
            positive_count = 0
            negative_count = 0
            
            for item in all_items:
                title = item.get("title", "").lower()
                
                for keyword in positive_keywords:
                    if keyword in title:
                        positive_count += 1
                
                for keyword in negative_keywords:
                    if keyword in title:
                        negative_count += 1
            
            total = positive_count + negative_count
            if total == 0:
                return 0.0
            
            sentiment = (positive_count - negative_count) / total
            return max(-1.0, min(1.0, sentiment))
            
        except Exception as e:
            self._available = False
            return None
    
    @property
    def is_available(self) -> bool:
        return self._available
