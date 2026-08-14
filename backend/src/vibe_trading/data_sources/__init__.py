"""
External Data Layer

Unified data source architecture with:
- Core layer: K-line, indicators, alpha factors, skills (shared between live and backtest)
- Plugin layer: Sentiment, liquidation (optional, live-only)
- Smart routing with circuit breaker and health monitoring
- Evidence gate for paper-to-live transition
"""

from .base import UnifiedDataSource, DataResult, Kline
from .cache import LRUCache
from .circuit_breaker import CircuitBreaker
from .health import HealthMonitor
from .router import SmartRouter

__all__ = [
    "UnifiedDataSource",
    "DataResult",
    "Kline",
    "LRUCache",
    "CircuitBreaker",
    "HealthMonitor",
    "SmartRouter",
]
