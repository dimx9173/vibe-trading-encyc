"""Tests for P3.2 Memory Upgrade components"""
import pytest
import tempfile
from pathlib import Path

from vibe_trading.memory.fts5_memory import FTS5Memory, FTS5Entry
from vibe_trading.memory.compression import ContextCompressor, CompressionConfig
from vibe_trading.memory.skill_manager import SkillManager, Skill


class TestFTS5Memory:
    """Test FTS5 memory backend"""

    @pytest.fixture
    def fts5_memory(self):
        """Create temporary FTS5 memory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_fts5.db"
            memory = FTS5Memory(str(db_path))
            yield memory

    def test_add_memory(self, fts5_memory):
        """Test adding memory"""
        memory_id = fts5_memory.add_memory(
            situation="BTC breakout above resistance",
            advice="Enter long position with 2% risk",
            pnl=5.5,
            symbol="BTCUSDT",
            tags="breakout,long",
        )
        assert memory_id is not None
        assert memory_id > 0

    def test_search_memory(self, fts5_memory):
        """Test searching memory"""
        fts5_memory.add_memory(
            situation="BTC breakout above resistance",
            advice="Enter long position",
            pnl=5.5,
            symbol="BTCUSDT",
        )
        fts5_memory.add_memory(
            situation="ETH bearish divergence",
            advice="Consider short position",
            pnl=-2.3,
            symbol="ETHUSDT",
        )

        results = fts5_memory.search("breakout")
        assert len(results) > 0
        assert any("breakout" in r.situation.lower() for r in results)

    def test_search_with_symbol_filter(self, fts5_memory):
        """Test search with symbol filter"""
        fts5_memory.add_memory("BTC pump", "Buy BTC", symbol="BTCUSDT")
        fts5_memory.add_memory("ETH pump", "Buy ETH", symbol="ETHUSDT")

        results = fts5_memory.search("pump", symbol_filter="BTCUSDT")
        assert all(r.symbol == "BTCUSDT" for r in results)

    def test_get_memory(self, fts5_memory):
        """Test getting memory by ID"""
        memory_id = fts5_memory.add_memory("Test situation", "Test advice")
        memory = fts5_memory.get_memory(memory_id)

        assert memory is not None
        assert memory.situation == "Test situation"
        assert memory.advice == "Test advice"

    def test_update_memory(self, fts5_memory):
        """Test updating memory"""
        memory_id = fts5_memory.add_memory("Old situation", "Old advice")
        fts5_memory.update_memory(memory_id, situation="New situation")

        memory = fts5_memory.get_memory(memory_id)
        assert memory.situation == "New situation"

    def test_delete_memory(self, fts5_memory):
        """Test deleting memory"""
        memory_id = fts5_memory.add_memory("Test", "Test")
        result = fts5_memory.delete_memory(memory_id)

        assert result is True
        assert fts5_memory.get_memory(memory_id) is None

    def test_get_all_memories(self, fts5_memory):
        """Test getting all memories"""
        fts5_memory.add_memory("Memory 1", "Advice 1")
        fts5_memory.add_memory("Memory 2", "Advice 2")

        memories = fts5_memory.get_all_memories()
        assert len(memories) == 2

    def test_get_stats(self, fts5_memory):
        """Test getting statistics"""
        fts5_memory.add_memory("Test 1", "Advice 1", pnl=5.0, symbol="BTCUSDT")
        fts5_memory.add_memory("Test 2", "Advice 2", pnl=-2.0, symbol="ETHUSDT")

        stats = fts5_memory.get_stats()
        assert stats["total_memories"] == 2
        assert stats["unique_symbols"] == 2
        assert stats["memories_with_pnl"] == 2

    def test_clear(self, fts5_memory):
        """Test clearing all memories"""
        fts5_memory.add_memory("Test", "Advice")
        fts5_memory.clear()

        memories = fts5_memory.get_all_memories()
        assert len(memories) == 0


class TestContextCompressor:
    """Test context compression layer"""

    def test_level0_no_compression(self):
        """Test level 0: no compression"""
        compressor = ContextCompressor()
        memories = [
            FTS5Entry(id=1, situation="Test situation", advice="Test advice", pnl=5.0),
        ]

        result = compressor.compress_memories(memories, target_tokens=10000)
        assert "Test situation" in result
        assert "Test advice" in result

    def test_level1_light_compression(self):
        """Test level 1: light compression"""
        compressor = ContextCompressor()
        memories = [
            FTS5Entry(id=1, situation="Long situation text", advice="Long advice text", pnl=5.0),
        ]

        result = compressor._level1_light_compression(memories)
        assert "#1:" in result
        assert "Long situation text" in result

    def test_level2_medium_compression(self):
        """Test level 2: medium compression"""
        compressor = ContextCompressor()
        memories = [
            FTS5Entry(id=1, situation="Situation", advice="Advice", pnl=5.0),
        ]

        result = compressor._level2_medium_compression(memories)
        assert "#1:" in result
        assert "PnL: 5.00%" in result

    def test_level3_heavy_compression(self):
        """Test level 3: heavy compression"""
        compressor = ContextCompressor()
        memories = [
            FTS5Entry(id=1, situation="S1", advice="Advice 1", pnl=10.0),
            FTS5Entry(id=2, situation="S2", advice="Advice 2", pnl=-5.0),
        ]

        result = compressor._level3_heavy_compression(memories)
        assert "-" in result
        # Should be sorted by absolute PnL
        assert "Advice 1" in result

    def test_level4_extreme_compression(self):
        """Test level 4: extreme compression"""
        compressor = ContextCompressor()
        memories = [
            FTS5Entry(id=1, situation="BTC breakout", advice="Buy BTC", pnl=5.0),
            FTS5Entry(id=2, situation="ETH breakdown", advice="Sell ETH", pnl=-3.0),
        ]

        result = compressor._level4_extreme_compression(memories)
        assert "2 memories" in result
        assert "avg PnL" in result

    def test_auto_compression_level_selection(self):
        """Test automatic compression level selection"""
        compressor = ContextCompressor(CompressionConfig(max_tokens=100))
        memories = [
            FTS5Entry(id=i, situation=f"Situation {i}" * 10, advice=f"Advice {i}" * 10)
            for i in range(5)
        ]

        result = compressor.compress_memories(memories, target_tokens=50)
        # Should compress to fit within target
        assert len(result.split()) * 1.3 <= 100  # Some tolerance


class TestSkillManager:
    """Test skill CRUD manager"""

    @pytest.fixture
    def skill_manager(self):
        """Create temporary skill manager"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SkillManager(storage_dir=tmpdir)
            yield manager

    def test_create_skill(self, skill_manager):
        """Test creating skill"""
        skill = skill_manager.create_skill(
            name="Test Skill",
            description="A test skill",
            category="testing",
        )

        assert skill.id is not None
        assert skill.name == "Test Skill"
        assert skill.category == "testing"

    def test_get_skill(self, skill_manager):
        """Test getting skill by ID"""
        skill = skill_manager.create_skill("Test", "Description")
        retrieved = skill_manager.get_skill(skill.id)

        assert retrieved is not None
        assert retrieved.id == skill.id

    def test_get_skill_by_name(self, skill_manager):
        """Test getting skill by name"""
        skill_manager.create_skill("Unique Skill", "Description")
        retrieved = skill_manager.get_skill_by_name("Unique Skill")

        assert retrieved is not None
        assert retrieved.name == "Unique Skill"

    def test_list_skills(self, skill_manager):
        """Test listing skills"""
        skill_manager.create_skill("Skill 1", "Desc 1", category="cat1")
        skill_manager.create_skill("Skill 2", "Desc 2", category="cat2")

        skills = skill_manager.list_skills()
        assert len(skills) == 2

    def test_list_skills_by_category(self, skill_manager):
        """Test listing skills by category"""
        skill_manager.create_skill("Skill 1", "Desc 1", category="cat1")
        skill_manager.create_skill("Skill 2", "Desc 2", category="cat2")

        skills = skill_manager.list_skills(category="cat1")
        assert len(skills) == 1
        assert skills[0].category == "cat1"

    def test_update_skill(self, skill_manager):
        """Test updating skill"""
        skill = skill_manager.create_skill("Old Name", "Description")
        updated = skill_manager.update_skill(skill.id, name="New Name")

        assert updated is not None
        assert updated.name == "New Name"

    def test_delete_skill(self, skill_manager):
        """Test deleting skill"""
        skill = skill_manager.create_skill("Test", "Description")
        result = skill_manager.delete_skill(skill.id)

        assert result is True
        assert skill_manager.get_skill(skill.id) is None

    def test_enable_disable_skill(self, skill_manager):
        """Test enabling/disabling skill"""
        skill = skill_manager.create_skill("Test", "Description")

        disabled = skill_manager.disable_skill(skill.id)
        assert disabled is not None
        assert disabled.enabled is False

        enabled = skill_manager.enable_skill(skill.id)
        assert enabled is not None
        assert enabled.enabled is True

    def test_search_skills(self, skill_manager):
        """Test searching skills"""
        skill_manager.create_skill("BTC Analysis", "Analyze BTC")
        skill_manager.create_skill("ETH Analysis", "Analyze ETH")

        results = skill_manager.search_skills("BTC")
        assert len(results) == 1
        assert results[0].name == "BTC Analysis"

    def test_get_categories(self, skill_manager):
        """Test getting categories"""
        skill_manager.create_skill("Skill 1", "Desc 1", category="cat1")
        skill_manager.create_skill("Skill 2", "Desc 2", category="cat2")

        categories = skill_manager.get_categories()
        assert "cat1" in categories
        assert "cat2" in categories

    def test_get_stats(self, skill_manager):
        """Test getting statistics"""
        skill_manager.create_skill("Skill 1", "Desc 1")
        skill_manager.create_skill("Skill 2", "Desc 2")

        stats = skill_manager.get_stats()
        assert stats["total_skills"] == 2
        assert stats["enabled"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
