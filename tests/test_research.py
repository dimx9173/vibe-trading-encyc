"""
Tests for P3 Research Modules

Tests for:
- Research models (Hypothesis, ResearchGoal)
- Research database
- Hypothesis Registry
- Goal Manager
"""
import pytest
import asyncio
from datetime import datetime
from typing import List

from vibe_trading.research.models import (
    Hypothesis, HypothesisStatus,
    ResearchGoal, GoalStatus, GoalChecklistItem
)
from vibe_trading.research.database import ResearchDatabase
from vibe_trading.research.registry import HypothesisRegistry
from vibe_trading.research.goal_manager import GoalManager


# ============================================================================
# Model Tests
# ============================================================================

class TestHypothesisModel:
    """Hypothesis model tests"""
    
    def test_create_hypothesis(self):
        """Test creating a hypothesis"""
        hyp = Hypothesis(
            id="test_001",
            title="Test Hypothesis",
            description="A test hypothesis",
            status=HypothesisStatus.DRAFT,
            tags=["test", "example"],
            author="Test Author"
        )
        
        assert hyp.id == "test_001"
        assert hyp.title == "Test Hypothesis"
        assert hyp.status == HypothesisStatus.DRAFT
        assert len(hyp.tags) == 2
    
    def test_hypothesis_to_dict(self):
        """Test hypothesis serialization"""
        hyp = Hypothesis(
            id="test_002",
            title="Test",
            description="Test description",
            status=HypothesisStatus.ACTIVE
        )
        
        data = hyp.to_dict()
        
        assert data["id"] == "test_002"
        assert data["title"] == "Test"
        assert data["status"] == "active"
    
    def test_hypothesis_from_dict(self):
        """Test hypothesis deserialization"""
        data = {
            "id": "test_003",
            "title": "Test",
            "description": "Test",
            "status": "draft",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "evidence": [],
            "backtest_results": [],
            "live_results": [],
            "tags": [],
            "author": "",
            "notes": "",
            "validated_at": None,
            "invalidated_at": None,
            "invalidation_reason": ""
        }
        
        hyp = Hypothesis.from_dict(data)
        
        assert hyp.id == "test_003"
        assert hyp.status == HypothesisStatus.DRAFT


class TestResearchGoalModel:
    """ResearchGoal model tests"""
    
    def test_create_goal(self):
        """Test creating a research goal"""
        goal = ResearchGoal(
            id="goal_001",
            title="Test Goal",
            description="A test goal",
            status=GoalStatus.PLANNED,
            checklist=[
                GoalChecklistItem(id="item_1", description="Task 1"),
                GoalChecklistItem(id="item_2", description="Task 2"),
            ],
            budget_backtests=10
        )
        
        assert goal.id == "goal_001"
        assert len(goal.checklist) == 2
        assert goal.budget_backtests == 10
    
    def test_goal_completion_percentage(self):
        """Test goal completion calculation"""
        goal = ResearchGoal(
            id="test",
            title="Test",
            description="Test",
            checklist=[
                GoalChecklistItem(id="1", description="Task 1", completed=True),
                GoalChecklistItem(id="2", description="Task 2", completed=False),
                GoalChecklistItem(id="3", description="Task 3", completed=True),
            ]
        )
        
        percentage = goal.get_completion_percentage()
        
        assert percentage == pytest.approx(66.67, rel=0.1)
    
    def test_goal_to_dict(self):
        """Test goal serialization"""
        goal = ResearchGoal(
            id="test",
            title="Test",
            description="Test",
            status=GoalStatus.IN_PROGRESS
        )
        
        data = goal.to_dict()
        
        assert data["id"] == "test"
        assert data["status"] == "in_progress"


# ============================================================================
# Database Tests
# ============================================================================

class TestResearchDatabase:
    """Research database tests"""
    
    @pytest.fixture
    def db(self, tmp_path):
        """Create temporary database"""
        db_path = str(tmp_path / "test_research.db")
        return ResearchDatabase(db_path)
    
    @pytest.mark.asyncio
    async def test_save_and_get_hypothesis(self, db):
        """Test saving and retrieving a hypothesis"""
        hyp = Hypothesis(
            id="hyp_001",
            title="Test Hypothesis",
            description="Test description",
            status=HypothesisStatus.DRAFT
        )
        
        await db.save_hypothesis(hyp)
        retrieved = await db.get_hypothesis("hyp_001")
        
        assert retrieved is not None
        assert retrieved.id == "hyp_001"
        assert retrieved.title == "Test Hypothesis"
    
    @pytest.mark.asyncio
    async def test_get_all_hypotheses(self, db):
        """Test getting all hypotheses"""
        hyp1 = Hypothesis(id="hyp_1", title="Hyp 1", description="Desc 1", status=HypothesisStatus.DRAFT)
        hyp2 = Hypothesis(id="hyp_2", title="Hyp 2", description="Desc 2", status=HypothesisStatus.ACTIVE)
        
        await db.save_hypothesis(hyp1)
        await db.save_hypothesis(hyp2)
        
        all_hyps = await db.get_all_hypotheses()
        
        assert len(all_hyps) == 2
    
    @pytest.mark.asyncio
    async def test_search_hypotheses(self, db):
        """Test searching hypotheses"""
        hyp = Hypothesis(
            id="hyp_search",
            title="BTC Momentum Strategy",
            description="Momentum-based trading for Bitcoin",
            status=HypothesisStatus.DRAFT,
            tags=["btc", "momentum"]
        )
        
        await db.save_hypothesis(hyp)
        
        results = await db.search_hypotheses("BTC")
        
        assert len(results) == 1
        assert results[0].id == "hyp_search"
    
    @pytest.mark.asyncio
    async def test_save_and_get_goal(self, db):
        """Test saving and retrieving a research goal"""
        goal = ResearchGoal(
            id="goal_001",
            title="Test Goal",
            description="Test description",
            status=GoalStatus.PLANNED
        )
        
        await db.save_goal(goal)
        retrieved = await db.get_goal("goal_001")
        
        assert retrieved is not None
        assert retrieved.id == "goal_001"
    
    @pytest.mark.asyncio
    async def test_delete_hypothesis(self, db):
        """Test deleting a hypothesis"""
        hyp = Hypothesis(id="hyp_del", title="Delete Me", description="Test", status=HypothesisStatus.DRAFT)
        
        await db.save_hypothesis(hyp)
        await db.delete_hypothesis("hyp_del")
        
        retrieved = await db.get_hypothesis("hyp_del")
        
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_stress_500_hypotheses_roundtrip(self, db):
        """壓力測試：500 筆 hypothesis save→query→update→delete 循環（驗證無洩漏/效能退化）"""
        import time as _time
        N = 500

        # 批次寫入
        t0 = _time.time()
        for i in range(N):
            await db.save_hypothesis(
                Hypothesis(
                    id=f"stress_{i:04d}",
                    title=f"Stress Hypothesis {i}",
                    description=f"Generated for stress test {i}",
                    status=HypothesisStatus.DRAFT if i % 2 == 0 else HypothesisStatus.VALIDATED,
                    tags=["stress", f"batch{i % 10}"],
                )
            )
        write_elapsed = _time.time() - t0

        # 全量讀取 + 狀態過濾
        all_h = await db.get_all_hypotheses()
        assert len(all_h) == N
        validated = await db.get_all_hypotheses(status=HypothesisStatus.VALIDATED)
        assert len(validated) == N // 2

        # 單筆隨機讀取
        t1 = _time.time()
        for i in range(0, N, 7):  # ~72 筆
            h = await db.get_hypothesis(f"stress_{i:04d}")
            assert h is not None and h.title == f"Stress Hypothesis {i}"
        read_elapsed = _time.time() - t1

        # 搜尋（LIKE 掃描）
        tag_hits = await db.search_hypotheses("batch3")
        assert len(tag_hits) == N // 10

        # 更新（INSERT OR REPLACE 路徑）
        for i in range(0, N, 5):  # 100 筆更新
            h = await db.get_hypothesis(f"stress_{i:04d}")
            h.notes = "updated-in-stress"
            await db.save_hypothesis(h)
        re_read = await db.get_hypothesis("stress_0000")
        assert re_read.notes == "updated-in-stress"

        # 清理
        for i in range(N):
            await db.delete_hypothesis(f"stress_{i:04d}")
        assert len(await db.get_all_hypotheses()) == 0

        # 效能斷言：500 寫入 < 10s、72 讀取 < 5s（CI 安全上限，非嚴格基準）
        assert write_elapsed < 10.0, f"批量寫入過慢: {write_elapsed:.2f}s"
        assert read_elapsed < 5.0, f"批量讀取過慢: {read_elapsed:.2f}s"


# ============================================================================
# Registry Tests
# ============================================================================

class TestHypothesisRegistry:
    """Hypothesis registry tests"""
    
    @pytest.fixture
    def registry(self, tmp_path):
        """Create registry with temporary database"""
        db_path = str(tmp_path / "test_registry.db")
        db = ResearchDatabase(db_path)
        return HypothesisRegistry(db)
    
    @pytest.mark.asyncio
    async def test_create_hypothesis(self, registry):
        """Test creating a hypothesis through registry"""
        hyp = await registry.create(
            title="Test Hypothesis",
            description="Test description",
            tags=["test"],
            author="Test Author"
        )
        
        assert hyp.id.startswith("hyp_")
        assert hyp.title == "Test Hypothesis"
        assert hyp.status == HypothesisStatus.DRAFT
    
    @pytest.mark.asyncio
    async def test_lifecycle(self, registry):
        """Test hypothesis lifecycle transitions"""
        hyp = await registry.create(title="Test", description="Test")
        
        # DRAFT -> ACTIVE
        activated = await registry.activate(hyp.id)
        assert activated is not None
        assert activated.status == HypothesisStatus.ACTIVE
        
        # ACTIVE -> TESTING
        testing = await registry.start_testing(hyp.id)
        assert testing is not None
        assert testing.status == HypothesisStatus.TESTING
        
        # TESTING -> VALIDATED
        validated = await registry.validate(hyp.id, evidence={"source": "backtest"})
        assert validated is not None
        assert validated.status == HypothesisStatus.VALIDATED
        assert validated.validated_at is not None
    
    @pytest.mark.asyncio
    async def test_invalidate(self, registry):
        """Test invalidating a hypothesis"""
        hyp = await registry.create(title="Test", description="Test")
        await registry.activate(hyp.id)
        
        invalidated = await registry.invalidate(hyp.id, reason="Poor backtest results")
        
        assert invalidated is not None
        assert invalidated.status == HypothesisStatus.INVALIDATED
        assert invalidated.invalidation_reason == "Poor backtest results"
    
    @pytest.mark.asyncio
    async def test_search(self, registry):
        """Test searching hypotheses"""
        await registry.create(title="BTC Strategy", description="Bitcoin trading", tags=["btc"])
        await registry.create(title="ETH Strategy", description="Ethereum trading", tags=["eth"])
        
        results = await registry.search("BTC")
        
        assert len(results) == 1
        assert "BTC" in results[0].title


# ============================================================================
# Goal Manager Tests
# ============================================================================

class TestGoalManager:
    """Goal manager tests"""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create manager with temporary database"""
        db_path = str(tmp_path / "test_goals.db")
        db = ResearchDatabase(db_path)
        return GoalManager(db)
    
    @pytest.mark.asyncio
    async def test_create_goal(self, manager):
        """Test creating a research goal"""
        goal = await manager.create(
            title="Test Goal",
            description="Test description",
            checklist_items=["Task 1", "Task 2", "Task 3"],
            budget_backtests=10,
            tags=["test"]
        )
        
        assert goal.id.startswith("goal_")
        assert len(goal.checklist) == 3
        assert goal.budget_backtests == 10
    
    @pytest.mark.asyncio
    async def test_complete_item(self, manager):
        """Test completing a checklist item"""
        goal = await manager.create(
            title="Test",
            description="Test",
            checklist_items=["Task 1", "Task 2"]
        )
        
        item_id = goal.checklist[0].id
        updated = await manager.complete_item(goal.id, item_id, evidence="Done")
        
        assert updated is not None
        assert updated.checklist[0].completed is True
        assert updated.checklist[0].evidence == "Done"
    
    @pytest.mark.asyncio
    async def test_auto_complete(self, manager):
        """Test automatic goal completion when all items done"""
        goal = await manager.create(
            title="Test",
            description="Test",
            checklist_items=["Task 1", "Task 2"]
        )
        
        for item in goal.checklist:
            await manager.complete_item(goal.id, item.id)
        
        updated = await manager.get(goal.id)
        
        assert updated.status == GoalStatus.COMPLETED
        assert updated.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_use_budget(self, manager):
        """Test recording budget usage"""
        goal = await manager.create(
            title="Test",
            description="Test",
            budget_backtests=10
        )
        
        updated = await manager.use_budget(goal.id, backtests=3, capital=1000.0)
        
        assert updated is not None
        assert updated.budget_used == 3
        assert updated.budget_capital_used == 1000.0
    
    @pytest.mark.asyncio
    async def test_link_hypothesis(self, manager):
        """Test linking a hypothesis to a goal"""
        goal = await manager.create(title="Test", description="Test")
        
        updated = await manager.link_hypothesis(goal.id, "hyp_001")
        
        assert updated is not None
        assert "hyp_001" in updated.hypothesis_ids
    
    @pytest.mark.asyncio
    async def test_cancel_goal(self, manager):
        """Test cancelling a goal"""
        goal = await manager.create(title="Test", description="Test")
        
        cancelled = await manager.cancel(goal.id, notes="No longer relevant")
        
        assert cancelled is not None
        assert cancelled.status == GoalStatus.CANCELLED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
