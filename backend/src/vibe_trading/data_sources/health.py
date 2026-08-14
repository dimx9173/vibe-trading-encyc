"""
Health Monitor

Tracks data source health metrics:
- Success rate (EMA algorithm)
- Average response time
- Data freshness
- Request counts

Used by SmartRouter to calculate source priority.
"""
from datetime import datetime
from typing import Dict, Optional


class HealthMonitor:
    """Data source health monitor"""
    
    def __init__(self, ema_alpha: float = 0.1):
        self.ema_alpha = ema_alpha
        
        self._success_rates: Dict[str, float] = {}
        self._avg_latencies: Dict[str, float] = {}
        self._request_counts: Dict[str, int] = {}
        self._last_success_time: Dict[str, datetime] = {}
        self._last_request_time: Dict[str, datetime] = {}
    
    def record_success(self, source_name: str, latency_ms: float):
        """Record successful request"""
        # Update success rate with EMA
        current_rate = self._success_rates.get(source_name, 1.0)
        self._success_rates[source_name] = current_rate * (1 - self.ema_alpha) + 1.0 * self.ema_alpha
        
        # Update average latency with EMA
        current_latency = self._avg_latencies.get(source_name, latency_ms)
        self._avg_latencies[source_name] = current_latency * (1 - self.ema_alpha) + latency_ms * self.ema_alpha
        
        # Update timestamps
        self._last_success_time[source_name] = datetime.now()
        self._last_request_time[source_name] = datetime.now()
        
        # Update request count
        self._request_counts[source_name] = self._request_counts.get(source_name, 0) + 1
    
    def record_failure(self, source_name: str):
        """Record failed request"""
        # Update success rate with EMA
        current_rate = self._success_rates.get(source_name, 1.0)
        self._success_rates[source_name] = current_rate * (1 - self.ema_alpha) + 0.0 * self.ema_alpha
        
        # Update timestamp
        self._last_request_time[source_name] = datetime.now()
        
        # Update request count
        self._request_counts[source_name] = self._request_counts.get(source_name, 0) + 1
    
    def get_success_rate(self, source_name: str) -> float:
        """Get success rate (0-1)"""
        return self._success_rates.get(source_name, 1.0)
    
    def get_latency_score(self, source_name: str) -> float:
        """Get latency score (0-1, lower is better)"""
        avg_latency = self._avg_latencies.get(source_name, 100.0)
        # Normalize: <100ms = 1.0, >1000ms = 0.0
        return max(0.0, min(1.0, 1.0 - (avg_latency - 100) / 900))
    
    def get_freshness(self, source_name: str) -> float:
        """Get data freshness score (0-1)"""
        last_success = self._last_success_time.get(source_name)
        if not last_success:
            return 0.0
        
        age_seconds = (datetime.now() - last_success).total_seconds()
        # Normalize: <60s = 1.0, >600s = 0.0
        return max(0.0, min(1.0, 1.0 - (age_seconds - 60) / 540))
    
    def get_request_count(self, source_name: str) -> int:
        """Get total request count"""
        return self._request_counts.get(source_name, 0)
    
    def get_stats(self, source_name: str) -> Dict[str, float]:
        """Get all stats for source"""
        return {
            "success_rate": self.get_success_rate(source_name),
            "latency_score": self.get_latency_score(source_name),
            "freshness": self.get_freshness(source_name),
            "request_count": self.get_request_count(source_name),
        }
    
    def reset(self, source_name: str):
        """Reset all stats for source"""
        self._success_rates.pop(source_name, None)
        self._avg_latencies.pop(source_name, None)
        self._request_counts.pop(source_name, None)
        self._last_success_time.pop(source_name, None)
        self._last_request_time.pop(source_name, None)
