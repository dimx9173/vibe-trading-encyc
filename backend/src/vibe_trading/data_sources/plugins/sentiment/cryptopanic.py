"""
CryptoPanic Sentiment Plugin

Fetches news sentiment from CryptoPanic API.
Requires API key from https://cryptopanic.com/developers/api/
"""
import httpx
from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel
from .base import SentimentPlugin


class CryptoPanicPost(BaseModel):
    """CryptoPanic news post"""
    title: str
    source: str
    published_at: datetime
    sentiment_score: float
    confidence: float
    url: str
    currencies: List[str]


class CryptoPanicSentiment(SentimentPlugin):
    """CryptoPanic sentiment plugin"""
    
    def __init__(self, api_key: str, max_pages: int = 10):
        self.api_key = api_key
        self.max_pages = max_pages
        self.base_url = "https://cryptopanic.com/api/free/v1/posts/"
        self._available = True
        self._http_client = httpx.AsyncClient(timeout=10.0)
    
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """Get aggregated sentiment for symbol"""
        try:
            # Map symbol to CryptoPanic format
            symbol_map = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
            cc_symbol = symbol_map.get(symbol, "BTC")
            
            # Fetch posts with pagination
            all_posts = []
            page = 1
            
            while page <= self.max_pages:
                params = {
                    "auth_token": self.api_key,
                    "currencies": cc_symbol,
                    "filter": "hot",
                    "public": "true",
                    "page": page
                }
                
                response = await self._http_client.get(self.base_url, params=params)
                data = response.json()
                
                posts = data.get("results", [])
                all_posts.extend(posts)
                
                if not data.get("next"):
                    break
                page += 1
            
            if not all_posts:
                self._available = False
                return None
            
            # Calculate aggregated sentiment
            total_positive = 0
            total_negative = 0
            
            for post in all_posts:
                votes = post.get("votes", {})
                total_positive += votes.get("positive", 0)
                total_negative += votes.get("negative", 0)
            
            total_votes = total_positive + total_negative
            if total_votes == 0:
                return 0.0
            
            sentiment = (total_positive - total_negative) / total_votes
            return max(-1.0, min(1.0, sentiment))
            
        except Exception as e:
            self._available = False
            return None
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    async def close(self):
        """Close HTTP client"""
        await self._http_client.aclose()
