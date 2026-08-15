"""Tests for GoalManager — Wave D111."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.research.goal_manager import GoalManager
from vibe_trading.research.models import (
    GoalChecklistItem,
    GoalStatus,
    ResearchGoal,
)


def _goal(goal_id="goal_1", checklist=None, status=GoalStatus.PLANNED):
    return ResearchGoal(
        id=goal_id, title="t", description="d", status=status,
        checklist=checklist or [
            GoalChecklistItem(id="item_1", description="do thing"),
            GoalChecklistItem(id="item_2", description="do other"),
        ],
    )


def _manager(goal=None):
    db = MagicMock()
    db.get_goal = AsyncMock(return_value=goal)
    db.save_goal = AsyncMock(return_value=True)
    db.get_all_goals = AsyncMock(return_value=[])
    db.delete_goal = AsyncMock(return_value=True)
    m = GoalManager(db=db)
    return m, db


class TestGoalManager:
    @pytest.mark.asyncio
    async def test_create(self):
        m, db = _manager()
        goal = await m.create(title="Find alpha", description="d",
                              checklist_items=["a", "b"])
        assert goal.id.startswith("goal_")
        assert goal.status == GoalStatus.PLANNED
        assert len(goal.checklist) == 2
        db.save_goal.assert_called_once()

    @pytest.mark.asyncio
    async def test_get(self):
        g = _goal()
        m, db = _manager(g)
        assert await m.get("goal_1") is g

    @pytest.mark.asyncio
    async def test_update(self):
        g = _goal()
        m, db = _manager(g)
        assert await m.update(g) is True

    @pytest.mark.asyncio
    async def test_start(self):
        g = _goal()
        m, _ = _manager(g)
        started = await m.start("goal_1")
        assert started.status == GoalStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_start_wrong_status(self):
        g = _goal(status=GoalStatus.IN_PROGRESS)
        m, _ = _manager(g)
        assert await m.start("goal_1") is None

    @pytest.mark.asyncio
    async def test_start_missing(self):
        m, _ = _manager()  # get_goal 回 None (MagicMock default)
        assert await m.start("nope") is None

    @pytest.mark.asyncio
    async def test_complete_item(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.complete_item("goal_1", "item_1", evidence="proof")
        item = [i for i in goal.checklist if i.id == "item_1"][0]
        assert item.completed is True
        assert item.evidence == "proof"
        assert goal.status == GoalStatus.PLANNED  # 未完

    @pytest.mark.asyncio
    async def test_complete_all_items_auto_completes(self):
        g = _goal()
        m, _ = _manager(g)
        await m.complete_item("goal_1", "item_1")
        goal = await m.complete_item("goal_1", "item_2")
        assert goal.status == GoalStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_complete_item_missing_goal(self):
        m, _ = _manager()
        assert await m.complete_item("nope", "x") is None

    @pytest.mark.asyncio
    async def test_add_evidence(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.add_evidence("goal_1", {"type": "backtest"})
        assert goal.evidence_log[0]["type"] == "backtest"
        assert "timestamp" in goal.evidence_log[0]

    @pytest.mark.asyncio
    async def test_use_budget(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.use_budget("goal_1", backtests=2, capital=50.0)
        assert goal.budget_used == 2
        assert goal.budget_capital_used == 50.0

    @pytest.mark.asyncio
    async def test_link_hypothesis(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.link_hypothesis("goal_1", "hyp_1")
        assert "hyp_1" in goal.hypothesis_ids
        # 重複不加
        await m.link_hypothesis("goal_1", "hyp_1")
        assert len(goal.hypothesis_ids) == 1

    @pytest.mark.asyncio
    async def test_complete(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.complete("goal_1", notes="done")
        assert goal.status == GoalStatus.COMPLETED
        assert goal.completion_notes == "done"

    @pytest.mark.asyncio
    async def test_complete_already_done(self):
        g = _goal(status=GoalStatus.COMPLETED)
        m, _ = _manager(g)
        assert await m.complete("goal_1") is None

    @pytest.mark.asyncio
    async def test_cancel(self):
        g = _goal()
        m, _ = _manager(g)
        goal = await m.cancel("goal_1", notes="no")
        assert goal.status == GoalStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_blocked(self):
        g = _goal(status=GoalStatus.COMPLETED)
        m, _ = _manager(g)
        assert await m.cancel("goal_1") is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        m, db = _manager()
        await m.get_all()
        db.get_all_goals.assert_called_once_with(None)
        await m.get_all(GoalStatus.PLANNED)
        db.get_all_goals.assert_called_with(GoalStatus.PLANNED)

    @pytest.mark.asyncio
    async def test_delete(self):
        m, db = _manager()
        assert await m.delete("goal_1") is True

    def test_completion_percentage(self):
        g = _goal(checklist=[
            GoalChecklistItem(id="1", description="a", completed=True),
            GoalChecklistItem(id="2", description="b", completed=False),
        ])
        m, _ = _manager(g)
        assert m.get_completion_percentage(g) == 50.0

    def test_completion_percentage_empty(self):
        g = _goal(checklist=[])
        m, _ = _manager(g)
        assert m.get_completion_percentage(g) == 0.0
