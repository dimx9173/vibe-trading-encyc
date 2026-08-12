"""Research Goal runtime - manages long-term research objectives"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from .database import ResearchDatabase
from .models import GoalChecklistItem, GoalStatus, ResearchGoal


class GoalManager:
    """Manages research goals with checklist and budget tracking"""

    def __init__(self, db: Optional[ResearchDatabase] = None):
        self.db = db or ResearchDatabase()

    def create(
        self,
        title: str,
        description: str,
        checklist_items: Optional[List[str]] = None,
        budget_backtests: int = 10,
        tags: Optional[List[str]] = None,
    ) -> ResearchGoal:
        """Create a new research goal"""
        goal = ResearchGoal(
            id=f"goal_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            status=GoalStatus.PLANNED,
            budget_backtests=budget_backtests,
            tags=tags or [],
            checklist=[
                GoalChecklistItem(
                    id=f"item_{uuid.uuid4().hex[:6]}",
                    description=item,
                )
                for item in (checklist_items or [])
            ],
        )
        self.db.save_goal(goal)
        return goal

    def get(self, goal_id: str) -> Optional[ResearchGoal]:
        """Get a goal by ID"""
        return self.db.get_goal(goal_id)

    def list(
        self,
        status: Optional[GoalStatus] = None,
        limit: int = 100,
    ) -> List[ResearchGoal]:
        """List goals with filters"""
        return self.db.list_goals(status=status, limit=limit)

    def start(self, goal_id: str) -> Optional[ResearchGoal]:
        """Transition from PLANNED to IN_PROGRESS"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        if goal.status != GoalStatus.PLANNED:
            raise ValueError(f"Cannot start goal in {goal.status.value} status")
        goal.status = GoalStatus.IN_PROGRESS
        goal.updated_at = datetime.now()
        self.db.save_goal(goal)
        return goal

    def complete_item(
        self,
        goal_id: str,
        item_id: str,
        evidence: Optional[str] = None,
    ) -> Optional[ResearchGoal]:
        """Mark a checklist item as completed"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None

        for item in goal.checklist:
            if item.id == item_id:
                item.completed = True
                item.completed_at = datetime.now()
                item.evidence = evidence
                break

        goal.updated_at = datetime.now()

        # Auto-complete if all items done
        if all(item.completed for item in goal.checklist):
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = datetime.now()

        self.db.save_goal(goal)
        return goal

    def add_evidence(self, goal_id: str, evidence: str) -> Optional[ResearchGoal]:
        """Add evidence to the goal's evidence log"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        goal.evidence_log.append(evidence)
        goal.updated_at = datetime.now()
        self.db.save_goal(goal)
        return goal
    def use_budget(self, goal_id: str, amount: int = 1) -> Optional[ResearchGoal]:
        """Increment budget usage"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        if goal.budget_used + amount > goal.budget_backtests:
            raise ValueError(
                f"Budget overflow: using {amount} would exceed limit of {goal.budget_backtests} "
                f"(currently used: {goal.budget_used})"
            )
        goal.budget_used += amount
        goal.updated_at = datetime.now()
        self.db.save_goal(goal)
        return goal

    def link_hypothesis(self, goal_id: str, hypothesis_id: str) -> Optional[ResearchGoal]:
        """Link a hypothesis to this goal"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        if hypothesis_id not in goal.hypothesis_ids:
            goal.hypothesis_ids.append(hypothesis_id)
            goal.updated_at = datetime.now()
            self.db.save_goal(goal)
        return goal

    def cancel(self, goal_id: str) -> Optional[ResearchGoal]:
        """Cancel a goal"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        if goal.status in (GoalStatus.COMPLETED, GoalStatus.CANCELLED):
            raise ValueError(f"Cannot cancel goal in {goal.status.value} status")
        goal.status = GoalStatus.CANCELLED
        goal.updated_at = datetime.now()
        self.db.save_goal(goal)
        return goal

    def delete(self, goal_id: str) -> bool:
        """Delete a goal"""
        return self.db.delete_goal(goal_id)

    def get_progress(self, goal_id: str) -> Optional[float]:
        """Get completion percentage"""
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        return goal.completion_percentage
