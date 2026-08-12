"""Research models for Hypothesis Registry and Research Goals"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


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
    """A research hypothesis with evidence tracking"""
    id: str
    title: str
    description: str
    status: HypothesisStatus = HypothesisStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None

    # Evidence and backtest links
    evidence: List[str] = field(default_factory=list)
    backtest_ids: List[str] = field(default_factory=list)
    alpha_factors: List[str] = field(default_factory=list)

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
            "invalidation_reason": self.invalidation_reason,
            "evidence": self.evidence,
            "backtest_ids": self.backtest_ids,
            "alpha_factors": self.alpha_factors,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=HypothesisStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            invalidated_at=datetime.fromisoformat(data["invalidated_at"]) if data.get("invalidated_at") else None,
            invalidation_reason=data.get("invalidation_reason"),
            evidence=data.get("evidence", []),
            backtest_ids=data.get("backtest_ids", []),
            alpha_factors=data.get("alpha_factors", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class GoalChecklistItem:
    """A checklist item within a research goal"""
    id: str
    description: str
    completed: bool = False
    completed_at: Optional[datetime] = None
    evidence: Optional[str] = None


@dataclass
class ResearchGoal:
    """Long-term research objective with checklist and budget"""
    id: str
    title: str
    description: str
    status: GoalStatus = GoalStatus.PLANNED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Checklist
    checklist: List[GoalChecklistItem] = field(default_factory=list)

    # Budget (in terms of backtest runs or time)
    budget_backtests: int = 10
    budget_used: int = 0

    # Linked hypotheses
    hypothesis_ids: List[str] = field(default_factory=list)

    # Evidence log
    evidence_log: List[str] = field(default_factory=list)

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
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
            "hypothesis_ids": self.hypothesis_ids,
            "evidence_log": self.evidence_log,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchGoal":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=GoalStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            checklist=[
                GoalChecklistItem(
                    id=item["id"],
                    description=item["description"],
                    completed=item["completed"],
                    completed_at=datetime.fromisoformat(item["completed_at"]) if item.get("completed_at") else None,
                    evidence=item.get("evidence"),
                )
                for item in data.get("checklist", [])
            ],
            budget_backtests=data.get("budget_backtests", 10),
            budget_used=data.get("budget_used", 0),
            hypothesis_ids=data.get("hypothesis_ids", []),
            evidence_log=data.get("evidence_log", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    @property
    def completion_percentage(self) -> float:
        if not self.checklist:
            return 0.0
        completed = sum(1 for item in self.checklist if item.completed)
        return (completed / len(self.checklist)) * 100
