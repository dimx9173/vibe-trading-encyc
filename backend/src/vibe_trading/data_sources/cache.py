"""
LRU Cache with TTL

Provides caching for data sources with:
- LRU eviction when max size reached
- TTL-based expiration per data type
- Thread-safe for asyncio environment
"""
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, Tuple, Any, Optional


class LRUCache:
    """LRU + TTL Cache"""
    
    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, Tuple[datetime, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttls: Dict[str, timedelta] = {
            "kline": timedelta(minutes=1),
            "indicators": timedelta(minutes=5),
            "alpha_factors": timedelta(minutes=10),
            "sentiment": timedelta(minutes=5),
            "liquidation": timedelta(minutes=10),
        }
    
    def get(self, key: str, data_type: str) -> Optional[Any]:
        """Get from cache"""
        if key not in self._cache:
            return None
        
        timestamp, value = self._cache[key]
        ttl = self._ttls.get(data_type, timedelta(minutes=5))
        
        # Check if expired
        if datetime.now() - timestamp > ttl:
            del self._cache[key]
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return value
    
    def set(self, key: str, value: Any, data_type: str):
        """Set cache"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (datetime.now(), value)
        
        # LRU eviction
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
    
    def clear(self):
        """Clear all cache"""
        self._cache.clear()
    
    def size(self) -> int:
        """Get cache size"""
        return len(self._cache)
    
    def stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
        }
