"""Memory system monitoring and metrics collection"""
from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SearchMetric:
    """Search performance metric"""
    timestamp: datetime = field(default_factory=datetime.now)
    query: str = ""
    engine: str = "bm25"  # "bm25" or "fts5"
    latency_ms: float = 0.0
    results_count: int = 0
    top_k: int = 3


@dataclass
class CompressionMetric:
    """Compression performance metric"""
    timestamp: datetime = field(default_factory=datetime.now)
    original_tokens: int = 0
    compressed_tokens: int = 0
    compression_level: int = 0
    compression_ratio: float = 0.0


@dataclass
class SkillUsageMetric:
    """Skill usage metric"""
    timestamp: datetime = field(default_factory=datetime.now)
    skill_id: str = ""
    skill_name: str = ""
    action: str = ""  # "create", "read", "update", "delete", "search"
    success: bool = True


class MemoryMonitor:
    """
    Memory system monitor

    Tracks:
    - FTS5 search latency
    - Compression ratios
    - Skill usage statistics
    """

    def __init__(self):
        self.search_metrics: List[SearchMetric] = []
        self.compression_metrics: List[CompressionMetric] = []
        self.skill_usage_metrics: List[SkillUsageMetric] = []

    def record_search(
        self,
        query: str,
        engine: str,
        latency_ms: float,
        results_count: int,
        top_k: int = 3,
    ):
        """Record search performance"""
        metric = SearchMetric(
            query=query,
            engine=engine,
            latency_ms=latency_ms,
            results_count=results_count,
            top_k=top_k,
        )
        self.search_metrics.append(metric)

        logger.debug(
            f"Search: {engine} | Query: '{query}' | "
            f"Latency: {latency_ms:.1f}ms | Results: {results_count}"
        )

    def record_compression(
        self,
        original_tokens: int,
        compressed_tokens: int,
        compression_level: int,
    ):
        """Record compression performance"""
        ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        metric = CompressionMetric(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_level=compression_level,
            compression_ratio=ratio,
        )
        self.compression_metrics.append(metric)

        logger.debug(
            f"Compression: Level {compression_level} | "
            f"Original: {original_tokens} | Compressed: {compressed_tokens} | "
            f"Ratio: {ratio:.2%}"
        )

    def record_skill_usage(
        self,
        skill_id: str,
        skill_name: str,
        action: str,
        success: bool = True,
    ):
        """Record skill usage"""
        metric = SkillUsageMetric(
            skill_id=skill_id,
            skill_name=skill_name,
            action=action,
            success=success,
        )
        self.skill_usage_metrics.append(metric)

        logger.debug(
            f"Skill: {action} | ID: {skill_id} | Name: {skill_name} | "
            f"Success: {success}"
        )

    def get_search_stats(self, engine: Optional[str] = None) -> Dict[str, float]:
        """Get search performance statistics"""
        metrics = self.search_metrics
        if engine:
            metrics = [m for m in metrics if m.engine == engine]

        if not metrics:
            return {
                "total_searches": 0,
                "avg_latency_ms": 0.0,
                "min_latency_ms": 0.0,
                "max_latency_ms": 0.0,
            }

        latencies = [m.latency_ms for m in metrics]
        return {
            "total_searches": len(metrics),
            "avg_latency_ms": sum(latencies) / len(latencies),
            "min_latency_ms": min(latencies),
            "max_latency_ms": max(latencies),
            "avg_results": sum(m.results_count for m in metrics) / len(metrics),
        }

    def get_compression_stats(self) -> Dict[str, float]:
        """Get compression statistics"""
        if not self.compression_metrics:
            return {
                "total_compressions": 0,
                "avg_compression_ratio": 0.0,
            }

        ratios = [m.compression_ratio for m in self.compression_metrics]
        return {
            "total_compressions": len(self.compression_metrics),
            "avg_compression_ratio": sum(ratios) / len(ratios),
            "avg_original_tokens": sum(m.original_tokens for m in self.compression_metrics) / len(self.compression_metrics),
            "avg_compressed_tokens": sum(m.compressed_tokens for m in self.compression_metrics) / len(self.compression_metrics),
        }

    def get_skill_usage_stats(self) -> Dict[str, int]:
        """Get skill usage statistics"""
        if not self.skill_usage_metrics:
            return {
                "total_operations": 0,
                "successful_operations": 0,
                "failed_operations": 0,
            }

        total = len(self.skill_usage_metrics)
        successful = sum(1 for m in self.skill_usage_metrics if m.success)
        failed = total - successful

        return {
            "total_operations": total,
            "successful_operations": successful,
            "failed_operations": failed,
        }

    def get_comprehensive_stats(self) -> Dict[str, Dict]:
        """Get comprehensive memory system statistics"""
        return {
            "search": self.get_search_stats(),
            "fts5_search": self.get_search_stats(engine="fts5"),
            "bm25_search": self.get_search_stats(engine="bm25"),
            "compression": self.get_compression_stats(),
            "skill_usage": self.get_skill_usage_stats(),
        }

    def clear_metrics(self):
        """Clear all metrics"""
        self.search_metrics.clear()
        self.compression_metrics.clear()
        self.skill_usage_metrics.clear()


# Global monitor instance
_monitor: Optional[MemoryMonitor] = None


def get_memory_monitor() -> MemoryMonitor:
    """Get global memory monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = MemoryMonitor()
    return _monitor


def reset_memory_monitor():
    """Reset global memory monitor"""
    global _monitor
    _monitor = None
