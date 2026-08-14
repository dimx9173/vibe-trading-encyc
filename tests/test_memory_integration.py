"""Integration tests and performance benchmarks for P3.2 Memory Upgrade"""
import time
import tempfile
from pathlib import Path

import pytest

from vibe_trading.memory.fts5_memory import FTS5Memory
from vibe_trading.memory.compression import ContextCompressor
from vibe_trading.memory.skill_manager import SkillManager
from vibe_trading.memory.hybrid_memory import HybridMemory
from vibe_trading.memory.memory import BM25Memory


class TestHybridMemoryIntegration:
    """Test HybridMemory end-to-end integration"""

    @pytest.fixture
    def hybrid_memory(self):
        """Create temporary hybrid memory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkl_path = Path(tmpdir) / "memory.pkl"
            fts5_path = Path(tmpdir) / "memory_fts5.db"
            memory = HybridMemory(
                storage_path=str(pkl_path),
                fts5_db_path=str(fts5_path),
            )
            yield memory

    def test_add_and_retrieve(self, hybrid_memory):
        """Test adding and retrieving memories"""
        hybrid_memory.add_memory(
            situation="BTC breakout above 50000 resistance",
            advice="Enter long with 2% risk",
            pnl=5.5,
            symbol="BTCUSDT",
        )

        results = hybrid_memory.retrieve_relevant("breakout", top_k=3)
        assert len(results) > 0
        assert any("breakout" in r.lower() for r in results)

    def test_fts5_fallback_to_bm25(self, hybrid_memory):
        """Test FTS5 fallback when FTS5 fails"""
        # Disable FTS5
        hybrid_memory.use_fts5 = False
        hybrid_memory.fts5_memory = None

        hybrid_memory.add_memory("Test situation", "Test advice", pnl=3.0)

        # Should still work via BM25
        results = hybrid_memory.retrieve_relevant("test", top_k=3)
        assert len(results) > 0

    def test_save_and_load(self, hybrid_memory):
        """Test save and load cycle"""
        hybrid_memory.add_memory("Memory 1", "Advice 1", pnl=5.0)
        hybrid_memory.add_memory("Memory 2", "Advice 2", pnl=-2.0)

        hybrid_memory.save()

        # Create new instance
        new_memory = HybridMemory(
            storage_path=str(hybrid_memory.storage_path),
            fts5_db_path=str(hybrid_memory.fts5_memory.db_path) if hybrid_memory.fts5_memory else "./test.db",
        )

        assert new_memory.size() == 2

    def test_clear(self, hybrid_memory):
        """Test clearing all memories"""
        hybrid_memory.add_memory("Test", "Advice")
        hybrid_memory.clear()

        assert hybrid_memory.size() == 0

    def test_get_fts5_stats(self, hybrid_memory):
        """Test getting FTS5 statistics"""
        hybrid_memory.add_memory("Test 1", "Advice 1", pnl=5.0, symbol="BTCUSDT")
        hybrid_memory.add_memory("Test 2", "Advice 2", pnl=-2.0, symbol="ETHUSDT")

        stats = hybrid_memory.get_fts5_stats()
        assert stats is not None
        assert stats["total_memories"] == 2
        assert stats["unique_symbols"] == 2


class TestEndToEndWorkflow:
    """Test complete end-to-end workflow"""

    def test_full_workflow(self):
        """Test complete memory workflow"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Create hybrid memory
            memory = HybridMemory(
                storage_path=str(Path(tmpdir) / "memory.pkl"),
                fts5_db_path=str(Path(tmpdir) / "memory_fts5.db"),
            )

            # 2. Add memories
            memories_data = [
                ("BTC breakout above 50000", "Enter long", 5.5, "BTCUSDT"),
                ("ETH breakdown below 3000", "Enter short", -2.3, "ETHUSDT"),
                ("SOL pump on high volume", "Take profit", 8.2, "SOLUSDT"),
                ("ADA consolidation pattern", "Wait for breakout", 0.0, "ADAUSDT"),
                ("DOT trend reversal", "Exit position", -1.5, "DOTUSDT"),
            ]

            for situation, advice, pnl, symbol in memories_data:
                memory.add_memory(situation, advice, pnl=pnl, symbol=symbol)

            # 3. Search memories
            results = memory.retrieve_relevant("breakout", top_k=3)
            assert len(results) > 0

            # 4. Compress context
            compressor = ContextCompressor()
            fts5_results = memory.fts5_memory.search("breakout")
            compressed = compressor.compress_memories(fts5_results, target_tokens=500)
            assert len(compressed) > 0

            # 5. Create skill
            skill_manager = SkillManager(storage_dir=str(Path(tmpdir) / "skills"))
            skill = skill_manager.create_skill(
                name="Breakout Detector",
                description="Detect breakout patterns",
                category="technical_analysis",
            )
            assert skill.id is not None

            # 6. Save and reload
            memory.save()

            new_memory = HybridMemory(
                storage_path=str(Path(tmpdir) / "memory.pkl"),
                fts5_db_path=str(Path(tmpdir) / "memory_fts5.db"),
            )
            assert new_memory.size() == 5


class TestPerformanceBenchmark:
    """Performance benchmarks comparing BM25 vs FTS5"""

    def _generate_test_data(self, count: int):
        """Generate test memories"""
        data = []
        for i in range(count):
            data.append({
                "situation": f"BTC price movement pattern {i} with volume spike",
                "advice": f"Trading recommendation {i} based on technical analysis",
                "pnl": (i % 10) - 5,
                "symbol": ["BTCUSDT", "ETHUSDT", "SOLUSDT"][i % 3],
            })
        return data

    def test_bm25_search_performance(self):
        """Benchmark BM25 search performance"""
        memory = BM25Memory()
        data = self._generate_test_data(1000)

        for item in data:
            memory.add_memory(
                situation=item["situation"],
                advice=item["advice"],
                pnl=item["pnl"],
                symbol=item["symbol"],
            )

        start = time.time()
        for _ in range(10):
            memory.retrieve_relevant("BTC movement", top_k=5)
        bm25_time = time.time() - start

        print(f"\nBM25 search (1000 memories, 10 queries): {bm25_time:.3f}s")
        print(f"Average per query: {bm25_time/10*1000:.1f}ms")

    def test_fts5_search_performance(self):
        """Benchmark FTS5 search performance"""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = FTS5Memory(str(Path(tmpdir) / "test.db"))
            data = self._generate_test_data(1000)

            for item in data:
                memory.add_memory(
                    situation=item["situation"],
                    advice=item["advice"],
                    pnl=item["pnl"],
                    symbol=item["symbol"],
                )

            start = time.time()
            for _ in range(10):
                memory.search("BTC movement", top_k=5)
            fts5_time = time.time() - start

            print(f"\nFTS5 search (1000 memories, 10 queries): {fts5_time:.3f}s")
            print(f"Average per query: {fts5_time/10*1000:.1f}ms")

    def test_compression_performance(self):
        """Benchmark compression performance"""
        from vibe_trading.memory.fts5_memory import FTS5Entry

        memories = [
            FTS5Entry(
                id=i,
                situation=f"Long situation description {i} " * 5,
                advice=f"Detailed advice {i} " * 5,
                pnl=(i % 10) - 5,
            )
            for i in range(20)
        ]

        compressor = ContextCompressor()

        start = time.time()
        for level in range(5):
            compressor._compress_at_level(memories, level)
        compression_time = time.time() - start

        print(f"\nCompression (20 memories, 5 levels): {compression_time:.3f}s")
        print(f"Average per level: {compression_time/5*1000:.1f}ms")

    def test_skill_manager_performance(self):
        """Benchmark skill manager performance"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SkillManager(storage_dir=tmpdir)

            start = time.time()
            for i in range(100):
                manager.create_skill(
                    name=f"Skill {i}",
                    description=f"Description {i}",
                    category=f"category_{i % 5}",
                )
            create_time = time.time() - start

            start = time.time()
            for _ in range(10):
                manager.search_skills("Skill")
            search_time = time.time() - start

            print(f"\nSkill creation (100 skills): {create_time:.3f}s")
            print(f"Skill search (10 queries): {search_time:.3f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
