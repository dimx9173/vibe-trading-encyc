"""
Smart Router

Routes data requests to the best available source based on:
- Health metrics (success rate, latency, freshness)
- Circuit breaker state
- Cache availability
- Configured priority weights

Implements fallback chains for resilience.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime

from .base import UnifiedDataSource, DataResult
from .cache import LRUCache
from .circuit_breaker import CircuitBreaker
from .health import HealthMonitor


class SmartRouter:
    """Smart data source router"""
    
    def __init__(
        self,
        sources: List[UnifiedDataSource],
        cache: Optional[LRUCache] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        health_monitor: Optional[HealthMonitor] = None,
        weights: Optional[Dict[str, float]] = None
    ):
        self.sources = sources
        self.cache = cache or LRUCache()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.health_monitor = health_monitor or HealthMonitor()
        
        # Priority weights (sum to 1.0)
        self.weights = weights or {
            "freshness": 0.30,
            "latency": 0.25,
            "success_rate": 0.25,
            "completeness": 0.20,
        }
    
    async def route(
        self,
        symbol: str,
        data_type: str,
        **kwargs
    ) -> DataResult:
        """Route request to best source"""
        
        # 1. Check cache first
        cache_key = f"{symbol}:{data_type}"
        cached = self.cache.get(cache_key, data_type)
        if cached is not None:
            return DataResult(
                source="cache",
                symbol=symbol,
                data=cached,
                timestamp=datetime.now(),
                freshness_score=0.5,  # Cached data is somewhat fresh
                confidence=0.8
            )
        
        # 2. Calculate priority for available sources
        scored_sources = []
        for source in self.sources:
            source_name = source.__class__.__name__
            
            # Check circuit breaker
            if not self.circuit_breaker.is_available(source_name):
                continue
            
            # Calculate priority
            priority = self._calculate_priority(source_name)
            scored_sources.append((source, priority, source_name))
        
        # 3. Sort by priority (highest first)
        scored_sources.sort(key=lambda x: x[1], reverse=True)
        
        # 4. Try sources in order (fallback chain)
        last_error = None
        for source, priority, source_name in scored_sources:
            try:
                # Fetch data
                result = await source.fetch(symbol, **kwargs)
                
                # Record success
                self.health_monitor.record_success(source_name, 0)  # TODO: measure actual latency
                self.circuit_breaker.record_success(source_name)
                
                # Update cache
                self.cache.set(cache_key, result.data, data_type)
                
                return result
                
            except Exception as e:
                last_error = e
                self.health_monitor.record_failure(source_name)
                self.circuit_breaker.record_failure(source_name)
                continue
        
        # 5. All sources failed
        raise Exception(
            f"All data sources failed for {symbol}:{data_type}. "
            f"Last error: {last_error}"
        )
    
    def _calculate_priority(self, source_name: str) -> float:
        """Calculate source priority"""
        freshness = self.health_monitor.get_freshness(source_name)
        latency = self.health_monitor.get_latency_score(source_name)
        success = self.health_monitor.get_success_rate(source_name)
        
        # Completeness is source-specific (default to 1.0)
        completeness = 1.0
        
        return (
            freshness * self.weights["freshness"] +
            latency * self.weights["latency"] +
            success * self.weights["success_rate"] +
            completeness * self.weights["completeness"]
        )
    
    def get_source_stats(self) -> Dict[str, Dict[str, float]]:
        """Get stats for all sources"""
        stats = {}
        for source in self.sources:
            source_name = source.__class__.__name__
            stats[source_name] = {
                **self.health_monitor.get_stats(source_name),
                "circuit_state": self.circuit_breaker.get_state(source_name).value,
                "priority": self._calculate_priority(source_name),
            }
        return stats
