"""
Research Models

Defines data models for:
- Hypothesis: Trading hypotheses with evidence tracking
- ResearchGoal: Long-term research objectives with checklist and budget
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class HypothesisStatus(str, Enum):
    """Hypothesis lifecycle status"""
    DRAFT = "draft"
    ACTIVE = "active"
    TESTING = "testing"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


class GoalStatus(str, Enum):
    """Research goal status"""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Hypothesis:
    """Trading hypothesis with evidence tracking"""
    id: str
    title: str
    description: str
    status: HypothesisStatus = HypothesisStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Evidence tracking
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    backtest_results: List[Dict[str, Any]] = field(default_factory=list)
    live_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    author: str = ""
    notes: str = ""
    
    # Validation
    validated_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    invalidation_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "evidence": self.evidence,
            "backtest_results": self.backtest_results,
            "live_results": self.live_results,
            "tags": self.tags,
            "author": self.author,
            "notes": self.notes,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
            "invalidation_reason": self.invalidation_reason,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        """Create from dictionary"""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=HypothesisStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            evidence=data.get("evidence", []),
            backtest_results=data.get("backtest_results", []),
            live_results=data.get("live_results", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            notes=data.get("notes", ""),
            validated_at=datetime.fromisoformat(data["validated_at"]) if data.get("validated_at") else None,
            invalidated_at=datetime.fromisoformat(data["invalidated_at"]) if data.get("invalidated_at") else None,
            invalidation_reason=data.get("invalidation_reason", ""),
        )


@dataclass
class GoalChecklistItem:
    """Research goal checklist item"""
    id: str
    description: str
    completed: bool = False
    completed_at: Optional[datetime] = None
    evidence: str = ""


@dataclass
class ResearchGoal:
    """Long-term research objective"""
    id: str
    title: str
    description: str
    status: GoalStatus = GoalStatus.PLANNED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Checklist
    checklist: List[GoalChecklistItem] = field(default_factory=list)
    
    # Budget
    budget_backtests: int = 10
    budget_used: int = 0
    budget_capital: float = 0.0
    budget_capital_used: float = 0.0
    
    # Evidence log
    evidence_log: List[Dict[str, Any]] = field(default_factory=list)
    
    # Linked hypotheses
    hypothesis_ids: List[str] = field(default_factory=list)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    author: str = ""
    notes: str = ""
    
    # Completion
    completed_at: Optional[datetime] = None
    completion_notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "checklist": [
                {
                    "id": item.id,
                    "description": item.description,
                    "completed": item.completed,
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                    "evidence": item.evidence,
                }
                for item in self.checklist
            ],
            "budget_backtests": self.budget_backtests,
            "budget_used": self.budget_used,
            "budget_capital": self.budget_capital,
            "budget_capital_used": self.budget_capital_used,
            "evidence_log": self.evidence_log,
            "hypothesis_ids": self.hypothesis_ids,
            "tags": self.tags,
            "author": self.author,
            "notes": self.notes,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "completion_notes": self.completion_notes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchGoal":
        """Create from dictionary"""
        checklist = [
            GoalChecklistItem(
                id=item["id"],
                description=item["description"],
                completed=item["completed"],
                completed_at=datetime.fromisoformat(item["completed_at"]) if item.get("completed_at") else None,
                evidence=item.get("evidence", ""),
            )
            for item in data.get("checklist", [])
        ]
        
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=GoalStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            checklist=checklist,
            budget_backtests=data.get("budget_backtests", 10),
            budget_used=data.get("budget_used", 0),
            budget_capital=data.get("budget_capital", 0.0),
            budget_capital_used=data.get("budget_capital_used", 0.0),
            evidence_log=data.get("evidence_log", []),
            hypothesis_ids=data.get("hypothesis_ids", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            notes=data.get("notes", ""),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            completion_notes=data.get("completion_notes", ""),
        )
    
    def get_completion_percentage(self) -> float:
        """Get checklist completion percentage"""
        if not self.checklist:
            return 0.0
        
        completed = sum(1 for item in self.checklist if item.completed)
        return (completed / len(self.checklist)) * 100
