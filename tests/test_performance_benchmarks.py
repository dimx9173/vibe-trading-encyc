"""
Performance benchmarks for the external data layer (spec §6.2).

Measures latency of pure-computation paths that do NOT depend on external
APIs: cache hit, router priority, health scoring, circuit breaker, and
performance metrics. Assertions use conservative CI-safe ceilings — a
failure here signals a real regression, not benchmark noise.
"""
import time as _time

from vibe_trading.data_sources.cache import LRUCache
from vibe_trading.data_sources.circuit_breaker import CircuitBreaker
from vibe_trading.data_sources.health import HealthMonitor
from vibe_trading.data_sources.performance_tracker import PerformanceTracker, TradeRecord
from vibe_trading.data_sources.router import SmartRouter


class _MockSource:
    """Minimal source stub for SmartRouter"""

    def __init__(self, name: str):
        self.name = name

    async def fetch(self, *args, **kwargs):
        return {"source": self.name, "data": 1.0}


def _avg_us(fn, n: int) -> float:
    """Run fn n times, return average microseconds per call"""
    fn()  # warmup
    t0 = _time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = _time.perf_counter() - t0
    return elapsed / n * 1e6


# ---------------------------------------------------------------------------
# §6.2 緩存命中 < 1ms
# ---------------------------------------------------------------------------

class TestCacheLatency:
    def test_cache_hit_under_1ms(self):
        cache = LRUCache(max_size=1000)
        cache.set("btc", {"close": 50000.0}, "kline")

        avg = _avg_us(lambda: cache.get("btc", "kline"), n=2000)
        assert avg < 1000.0, f"cache hit avg {avg:.1f}us >= 1ms"

    def test_cache_set_under_1ms(self):
        cache = LRUCache(max_size=1000)
        avg = _avg_us(lambda: cache.set("k", 1.0, "kline"), n=2000)
        assert avg < 1000.0, f"cache set avg {avg:.1f}us >= 1ms"


# ---------------------------------------------------------------------------
# §6.2 智能路由決策 < 10ms
# ---------------------------------------------------------------------------

class TestRouterLatency:
    def test_router_priority_under_10ms(self):
        cache = LRUCache(max_size=100)
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        hm = HealthMonitor()
        router = SmartRouter(
            sources=[_MockSource("a"), _MockSource("b")],
            cache=cache,
            circuit_breaker=cb,
            health_monitor=hm,
        )
        hm.record_success("a", 50.0)
        hm.record_success("b", 120.0)

        avg = _avg_us(lambda: router._calculate_priority("a"), n=2000)
        assert avg < 10_000.0, f"router priority avg {avg:.1f}us >= 10ms"


# ---------------------------------------------------------------------------
# §6.2 健康監測 / 熔斷器（純計算路徑）
# ---------------------------------------------------------------------------

class TestHealthLatency:
    def test_health_scoring_under_1ms(self):
        hm = HealthMonitor()
        hm.record_success("src", 50.0)
        avg = _avg_us(
            lambda: (hm.get_success_rate("src"), hm.get_latency_score("src"), hm.get_freshness("src")),
            n=2000,
        )
        assert avg < 1000.0, f"health scoring avg {avg:.1f}us >= 1ms"

    def test_circuit_breaker_under_1ms(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        cb.record_failure("src")
        avg = _avg_us(lambda: cb.get_state("src"), n=2000)
        assert avg < 1000.0, f"circuit breaker avg {avg:.1f}us >= 1ms"


# ---------------------------------------------------------------------------
# §6.2 績效指標計算（本機數據，非外部 API）
# ---------------------------------------------------------------------------

class TestMetricsLatency:
    def test_metrics_on_100_trades_under_2ms(self, tmp_path):
        tracker = PerformanceTracker(str(tmp_path / "bench.db"))
        for i in range(100):
            tracker.record_trade(
                TradeRecord(
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=0.01,
                    entry_price=50_000 + i,
                    exit_price=50_000 + i + (10 if i % 2 else -10),
                    realized_pnl=50.0 if i % 2 else -40.0,
                )
            )
        avg = _avg_us(lambda: tracker.get_metrics(), n=200)
        assert avg < 2000.0, f"metrics avg {avg:.1f}us >= 2ms"
