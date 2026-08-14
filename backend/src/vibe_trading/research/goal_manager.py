"""
Research Goal Manager

Manages long-term research objectives with:
- Checklist tracking
- Budget management (backtests and capital)
- Evidence logging
- Hypothesis linking
"""
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from .models import ResearchGoal, GoalStatus, GoalChecklistItem
from .database import ResearchDatabase


class GoalManager:
    """Research goal lifecycle manager"""
    
    def __init__(self, db: Optional[ResearchDatabase] = None):
        self.db = db or ResearchDatabase()
    
    async def create(
        self,
        title: str,
        description: str,
        checklist_items: Optional[List[str]] = None,
        budget_backtests: int = 10,
        budget_capital: float = 0.0,
        tags: Optional[List[str]] = None,
        author: str = ""
    ) -> ResearchGoal:
        """Create a new research goal in PLANNED status"""
        checklist = [
            GoalChecklistItem(
                id=f"item_{uuid.uuid4().hex[:6]}",
                description=item,
            )
            for item in (checklist_items or [])
        ]
        
        goal = ResearchGoal(
            id=f"goal_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            status=GoalStatus.PLANNED,
            checklist=checklist,
            budget_backtests=budget_backtests,
            budget_capital=budget_capital,
            tags=tags or [],
            author=author,
        )
        
        await self.db.save_goal(goal)
        return goal
    
    async def get(self, goal_id: str) -> Optional[ResearchGoal]:
        """Get a research goal by ID"""
        return await self.db.get_goal(goal_id)
    
    async def update(self, goal: ResearchGoal) -> bool:
        """Update a research goal"""
        goal.updated_at = datetime.now()
        return await self.db.save_goal(goal)
    
    async def start(self, goal_id: str) -> Optional[ResearchGoal]:
        """Transition from PLANNED to IN_PROGRESS"""
        goal = await self.get(goal_id)
        if not goal or goal.status != GoalStatus.PLANNED:
            return None
        
        goal.status = GoalStatus.IN_PROGRESS
        await self.update(goal)
        return goal
    
    async def complete_item(
        self,
        goal_id: str,
        item_id: str,
        evidence: str = ""
    ) -> Optional[ResearchGoal]:
        """Mark a checklist item as completed"""
        goal = await self.get(goal_id)
        if not goal:
            return None
        
        for item in goal.checklist:
            if item.id == item_id:
                item.completed = True
                item.completed_at = datetime.now()
                item.evidence = evidence
                break
        
        # Check if all items are completed
        if all(item.completed for item in goal.checklist):
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = datetime.now()
        
        await self.update(goal)
        return goal
    
    async def add_evidence(
        self,
        goal_id: str,
        evidence: Dict[str, Any]
    ) -> Optional[ResearchGoal]:
        """Add evidence to the goal's evidence log"""
        goal = await self.get(goal_id)
        if not goal:
            return None
        
        goal.evidence_log.append({
            **evidence,
            "timestamp": datetime.now().isoformat(),
        })
        
        await self.update(goal)
        return goal
    
    async def use_budget(
        self,
        goal_id: str,
        backtests: int = 1,
        capital: float = 0.0
    ) -> Optional[ResearchGoal]:
        """Record budget usage"""
        goal = await self.get(goal_id)
        if not goal:
            return None
        
        goal.budget_used += backtests
        goal.budget_capital_used += capital
        
        await self.update(goal)
        return goal
    
    async def link_hypothesis(
        self,
        goal_id: str,
        hypothesis_id: str
    ) -> Optional[ResearchGoal]:
        """Link a hypothesis to this goal"""
        goal = await self.get(goal_id)
        if not goal:
            return None
        
        if hypothesis_id not in goal.hypothesis_ids:
            goal.hypothesis_ids.append(hypothesis_id)
            await self.update(goal)
        
        return goal
    
    async def complete(
        self,
        goal_id: str,
        notes: str = ""
    ) -> Optional[ResearchGoal]:
        """Mark goal as completed"""
        goal = await self.get(goal_id)
        if not goal or goal.status == GoalStatus.COMPLETED:
            return None
        
        goal.status = GoalStatus.COMPLETED
        goal.completed_at = datetime.now()
        goal.completion_notes = notes
        
        await self.update(goal)
        return goal
    
    async def cancel(
        self,
        goal_id: str,
        notes: str = ""
    ) -> Optional[ResearchGoal]:
        """Cancel a research goal"""
        goal = await self.get(goal_id)
        if not goal or goal.status in (GoalStatus.COMPLETED, GoalStatus.CANCELLED):
            return None
        
        goal.status = GoalStatus.CANCELLED
        goal.completion_notes = notes
        
        await self.update(goal)
        return goal
    
    async def get_all(
        self,
        status: Optional[GoalStatus] = None
    ) -> List[ResearchGoal]:
        """Get all research goals, optionally filtered by status"""
        return await self.db.get_all_goals(status)
    
    async def delete(self, goal_id: str) -> bool:
        """Delete a research goal"""
        return await self.db.delete_goal(goal_id)
    
    def get_completion_percentage(self, goal: ResearchGoal) -> float:
        """Get checklist completion percentage"""
        return goal.get_completion_percentage()
