"""Tests for MemoryMonitor — Wave D114."""
from vibe_trading.memory.monitor import (
    MemoryMonitor,
    get_memory_monitor,
    reset_memory_monitor,
)


class TestMemoryMonitor:
    def test_record_search(self):
        m = MemoryMonitor()
        m.record_search("alpha", "bm25", 12.5, 3)
        stats = m.get_search_stats()
        assert stats["total_searches"] == 1
        assert stats["avg_latency_ms"] == 12.5
        assert stats["max_latency_ms"] == 12.5

    def test_search_stats_empty(self):
        m = MemoryMonitor()
        stats = m.get_search_stats()
        assert stats["total_searches"] == 0

    def test_search_stats_engine_filter(self):
        m = MemoryMonitor()
        m.record_search("a", "bm25", 10.0, 2)
        m.record_search("b", "fts5", 20.0, 4)
        bm = m.get_search_stats(engine="bm25")
        assert bm["total_searches"] == 1
        assert bm["avg_latency_ms"] == 10.0
        fts = m.get_search_stats(engine="fts5")
        assert fts["total_searches"] == 1

    def test_search_stats_empty_engine(self):
        m = MemoryMonitor()
        stats = m.get_search_stats(engine="nope")
        assert stats["total_searches"] == 0

    def test_search_avg_results(self):
        m = MemoryMonitor()
        m.record_search("a", "bm25", 10.0, 2)
        m.record_search("b", "bm25", 20.0, 4)
        stats = m.get_search_stats()
        assert stats["avg_results"] == 3.0

    def test_record_compression(self):
        m = MemoryMonitor()
        m.record_compression(1000, 300, 3)
        stats = m.get_compression_stats()
        assert stats["total_compressions"] == 1
        assert stats["avg_compression_ratio"] == 0.3

    def test_compression_zero_original(self):
        m = MemoryMonitor()
        m.record_compression(0, 0, 1)
        stats = m.get_compression_stats()
        assert stats["avg_compression_ratio"] == 1.0

    def test_compression_empty(self):
        m = MemoryMonitor()
        stats = m.get_compression_stats()
        assert stats["total_compressions"] == 0

    def test_record_skill_usage(self):
        m = MemoryMonitor()
        m.record_skill_usage("s1", "search", "load", success=True)
        m.record_skill_usage("s2", "mine", "save", success=False)
        stats = m.get_skill_usage_stats()
        assert stats["total_operations"] == 2
        assert stats["successful_operations"] == 1
        assert stats["failed_operations"] == 1

    def test_skill_usage_empty(self):
        m = MemoryMonitor()
        stats = m.get_skill_usage_stats()
        assert stats["total_operations"] == 0

    def test_get_comprehensive_stats(self):
        m = MemoryMonitor()
        m.record_search("q", "bm25", 5.0, 1)
        m.record_compression(100, 50, 2)
        m.record_skill_usage("s", "n", "load")
        stats = m.get_comprehensive_stats()
        assert stats["search"]["total_searches"] == 1
        assert stats["bm25_search"]["total_searches"] == 1
        assert stats["fts5_search"]["total_searches"] == 0
        assert stats["compression"]["total_compressions"] == 1
        assert stats["skill_usage"]["total_operations"] == 1

    def test_clear_metrics(self):
        m = MemoryMonitor()
        m.record_search("q", "bm25", 1.0, 1)
        m.record_compression(10, 5, 1)
        m.record_skill_usage("s", "n", "load")
        m.clear_metrics()
        assert m.get_search_stats()["total_searches"] == 0
        assert m.get_compression_stats()["total_compressions"] == 0
        assert m.get_skill_usage_stats()["total_operations"] == 0


class TestMonitorSingleton:
    def test_get_memory_monitor(self):
        reset_memory_monitor()
        a = get_memory_monitor()
        b = get_memory_monitor()
        assert a is b
        reset_memory_monitor()
        c = get_memory_monitor()
        assert c is not a
        reset_memory_monitor()
