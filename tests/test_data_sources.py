"""
Tests for External Data Layer Core Modules

Tests for:
- LRUCache
- CircuitBreaker
- HealthMonitor
- SmartRouter
- Plugin interfaces
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from vibe_trading.data_sources.cache import LRUCache
from vibe_trading.data_sources.circuit_breaker import CircuitBreaker, CircuitState
from vibe_trading.data_sources.health import HealthMonitor
from vibe_trading.data_sources.router import SmartRouter
from vibe_trading.data_sources.base import DataResult, Kline
from vibe_trading.data_sources.plugins.sentiment.base import SentimentPlugin
from vibe_trading.data_sources.plugins.sentiment.null import NullSentiment


# ============================================================================
# LRUCache Tests
# ============================================================================

class TestLRUCache:
    """LRU Cache tests"""
    
    def test_cache_set_get(self):
        """Test basic set and get"""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1", "indicators")
        
        result = cache.get("key1", "indicators")
        assert result == "value1"
    
    def test_cache_ttl_expiry(self):
        """Test TTL expiration"""
        import time
        cache = LRUCache(max_size=100)
        
        # Set with very short TTL by manipulating internal state
        cache.set("key1", "value1", "indicators")
        
        # Manually expire the entry by setting an old timestamp
        cache._cache["key1"] = (time.time() - 600, "value1")
        
        result = cache.get("key1", "indicators")
        assert result is None
    
    def test_sync_cached_ttl_expiry(self):
        """sync_cached 的 ttl 參數真實生效：過期後重新計算"""
        import time
        from vibe_trading.data_sources.cache import sync_cached

        calls = {"n": 0}

        @sync_cached(ttl=0.05)
        def compute(x):
            calls["n"] += 1
            return x * 2

        assert compute(21) == 42
        assert calls["n"] == 1
        assert compute(21) == 42
        assert calls["n"] == 1  # 命中快取
        time.sleep(0.06)
        assert compute(21) == 42
        assert calls["n"] == 2  # TTL 過期 → 重算
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when max size reached"""
        cache = LRUCache(max_size=3)
        
        cache.set("key1", "value1", "indicators")
        cache.set("key2", "value2", "indicators")
        cache.set("key3", "value3", "indicators")
        
        # Access key1 to make it recently used
        cache.get("key1", "indicators")
        
        # Add key4, should evict key2 (least recently used)
        cache.set("key4", "value4", "indicators")
        
        assert cache.get("key1", "indicators") == "value1"  # Still there
        assert cache.get("key2", "indicators") is None      # Evicted
        assert cache.get("key3", "indicators") == "value3"  # Still there
        assert cache.get("key4", "indicators") == "value4"  # New entry
    
    def test_cache_max_size(self):
        """Test cache respects max size"""
        cache = LRUCache(max_size=5)
        
        for i in range(10):
            cache.set(f"key{i}", f"value{i}", "indicators")
        
        assert cache.size() <= 5
    
    def test_cache_clear(self):
        """Test cache clear"""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1", "indicators")
        cache.set("key2", "value2", "indicators")
        
        cache.clear()
        
        assert cache.size() == 0
        assert cache.get("key1", "indicators") is None
    
    def test_cache_stats(self):
        """Test cache statistics"""
        cache = LRUCache(max_size=100)
        cache.set("key1", "value1", "indicators")
        
        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["max_size"] == 100


# ============================================================================
# CircuitBreaker Tests
# ============================================================================

class TestCircuitBreaker:
    """Circuit breaker tests"""
    
    def test_initial_state(self):
        """Test initial state is CLOSED"""
        cb = CircuitBreaker()
        assert cb.is_available("source1") == True
        assert cb.get_state("source1") == CircuitState.CLOSED
    
    def test_opens_after_failures(self):
        """Test circuit opens after threshold failures"""
        cb = CircuitBreaker(failure_threshold=3)
        
        # Record 3 failures
        cb.record_failure("source1")
        cb.record_failure("source1")
        cb.record_failure("source1")
        
        # Circuit should be open
        assert cb.is_available("source1") == False
        assert cb.get_state("source1") == CircuitState.OPEN
    
    def test_recovers_after_timeout(self):
        """Test circuit recovers after timeout"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        
        # Trip the circuit
        cb.record_failure("source1")
        cb.record_failure("source1")
        assert cb.is_available("source1") == False
        
        # Wait for recovery timeout
        import time
        time.sleep(1.1)
        
        # Should transition to HALF_OPEN
        assert cb.is_available("source1") == True
        assert cb.get_state("source1") == CircuitState.HALF_OPEN
    
    def test_half_open_testing(self):
        """Test HALF_OPEN allows limited calls after recovery"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60, half_open_max_calls=2)
        
        # Trip the circuit
        cb.record_failure("source1")
        cb.record_failure("source1")
        assert cb.is_available("source1") == False
        assert cb.get_state("source1") == CircuitState.OPEN
        
        # Manually set to HALF_OPEN for testing
        cb._states["source1"] = CircuitState.HALF_OPEN
        cb._half_open_calls["source1"] = 0
        
        # Should allow first call
        assert cb.is_available("source1") == True
        
        # Simulate first call
        cb._half_open_calls["source1"] = 1
        
        # Should allow second call
        assert cb.is_available("source1") == True
        
        # Simulate second call
        cb._half_open_calls["source1"] = 2
        
        # Third call should be blocked
        assert cb.is_available("source1") == False
    
    def test_success_resets_circuit(self):
        """Test success resets circuit to CLOSED"""
        cb = CircuitBreaker(failure_threshold=3)
        
        cb.record_failure("source1")
        cb.record_failure("source1")
        
        # Success should reset
        cb.record_success("source1")
        
        assert cb.get_state("source1") == CircuitState.CLOSED
        assert cb.is_available("source1") == True
    
    def test_multiple_sources(self):
        """Test circuit breaker tracks sources independently"""
        cb = CircuitBreaker(failure_threshold=2)
        
        cb.record_failure("source1")
        cb.record_failure("source1")
        
        # source1 should be open, source2 should be closed
        assert cb.is_available("source1") == False
        assert cb.is_available("source2") == True
    
    def test_reset(self):
        """Test manual reset"""
        cb = CircuitBreaker(failure_threshold=2)
        
        cb.record_failure("source1")
        cb.record_failure("source1")
        
        cb.reset("source1")
        
        assert cb.is_available("source1") == True
        assert cb.get_state("source1") == CircuitState.CLOSED


# ============================================================================
# HealthMonitor Tests
# ============================================================================

class TestHealthMonitor:
    """Health monitor tests"""
    
    def test_record_success(self):
        """Test recording successful request"""
        hm = HealthMonitor()
        hm.record_success("source1", 100.0)
        
        assert hm.get_success_rate("source1") > 0.9
        assert hm.get_request_count("source1") == 1
    
    def test_record_failure(self):
        """Test recording failed request"""
        hm = HealthMonitor()
        hm.record_success("source1", 100.0)
        hm.record_failure("source1")
        
        # Success rate should decrease
        assert hm.get_success_rate("source1") < 1.0
        assert hm.get_request_count("source1") == 2
    
    def test_ema_algorithm(self):
        """Test EMA smoothing"""
        hm = HealthMonitor(ema_alpha=0.1)
        
        # Record 10 successes
        for _ in range(10):
            hm.record_success("source1", 100.0)
        
        # Success rate should be close to 1.0
        assert hm.get_success_rate("source1") > 0.9
    
    def test_latency_score(self):
        """Test latency score normalization"""
        hm = HealthMonitor()
        
        # Fast latency (<100ms)
        hm.record_success("fast", 50.0)
        assert hm.get_latency_score("fast") > 0.9
        
        # Slow latency (>1000ms)
        hm.record_success("slow", 1500.0)
        assert hm.get_latency_score("slow") < 0.5
    
    def test_freshness(self):
        """Test freshness score"""
        hm = HealthMonitor()
        
        # No data
        assert hm.get_freshness("source1") == 0.0
        
        # Recent success
        hm.record_success("source1", 100.0)
        assert hm.get_freshness("source1") > 0.9
    
    def test_get_stats(self):
        """Test getting all stats"""
        hm = HealthMonitor()
        hm.record_success("source1", 100.0)
        
        stats = hm.get_stats("source1")
        assert "success_rate" in stats
        assert "latency_score" in stats
        assert "freshness" in stats
        assert "request_count" in stats
    
    def test_reset(self):
        """Test resetting stats"""
        hm = HealthMonitor()
        hm.record_success("source1", 100.0)
        
        hm.reset("source1")
        
        assert hm.get_success_rate("source1") == 1.0  # Default
        assert hm.get_request_count("source1") == 0


# ============================================================================
# Plugin Interface Tests
# ============================================================================

class TestSentimentPlugin:
    """Sentiment plugin tests"""
    
    @pytest.mark.asyncio
    async def test_null_sentiment(self):
        """Test null sentiment plugin"""
        plugin = NullSentiment()
        
        assert plugin.is_available == False
        result = await plugin.get_sentiment("BTCUSDT")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_plugin_interface(self):
        """Test plugin interface compliance"""
        plugin = NullSentiment()
        
        # Check required methods exist
        assert hasattr(plugin, 'get_sentiment')
        assert hasattr(plugin, 'is_available')
        assert hasattr(plugin, 'name')
        
        # Check name property
        assert plugin.name == "NullSentiment"


# ============================================================================
# SmartRouter Tests
# ============================================================================

class TestSmartRouter:
    """Smart router tests"""
    
    @pytest.mark.asyncio
    async def test_router_with_cache(self):
        """Test router uses cache"""
        # Create mock source
        class MockSource:
            def __init__(self):
                self.__class__.__name__ = "MockSource"
            
            async def fetch(self, symbol, **kwargs):
                return DataResult(
                    source="mock",
                    symbol=symbol,
                    data={"price": 50000},
                    timestamp=datetime.now(),
                    freshness_score=1.0,
                    confidence=0.9
                )
        
        cache = LRUCache()
        router = SmartRouter(sources=[MockSource()], cache=cache)
        
        # First call - should fetch from source
        result1 = await router.route("BTCUSDT", "indicators")
        assert result1.data["price"] == 50000
        
        # Second call - should use cache
        result2 = await router.route("BTCUSDT", "indicators")
        assert result2.source == "cache"
    
    def test_router_stats(self):
        """Test getting router stats"""
        class MockSource:
            def __init__(self):
                self.__class__.__name__ = "MockSource"
        
        router = SmartRouter(sources=[MockSource()])
        stats = router.get_source_stats()
        
        assert "MockSource" in stats
        assert "priority" in stats["MockSource"]


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests"""
    
    def test_cache_and_circuit_breaker(self):
        """Test cache and circuit breaker work together"""
        cache = LRUCache()
        cb = CircuitBreaker()
        
        # Cache some data
        cache.set("key1", "value1", "indicators")
        
        # Circuit breaker should not affect cache
        cb.record_failure("source1")
        
        # Cache should still work
        assert cache.get("key1", "indicators") == "value1"
    
    def test_health_monitor_and_router(self):
        """Test health monitor integrates with router"""
        hm = HealthMonitor()
        
        class MockSource:
            def __init__(self):
                self.__class__.__name__ = "MockSource"
        
        router = SmartRouter(sources=[MockSource()], health_monitor=hm)
        
        # Record some health data
        hm.record_success("MockSource", 100.0)
        
        # Router should use health data
        stats = router.get_source_stats()
        assert stats["MockSource"]["success_rate"] > 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
