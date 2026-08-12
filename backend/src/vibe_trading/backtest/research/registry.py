"""Hypothesis Registry - CRUD and lifecycle management"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from .database import ResearchDatabase
from .models import Hypothesis, HypothesisStatus


class HypothesisRegistry:
    """Manages the lifecycle of research hypotheses"""

    def __init__(self, db: Optional[ResearchDatabase] = None):
        self.db = db or ResearchDatabase()

    def create(
        self,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        alpha_factors: Optional[List[str]] = None,
    ) -> Hypothesis:
        """Create a new hypothesis in DRAFT status"""
        hypothesis = Hypothesis(
            id=f"hyp_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            status=HypothesisStatus.DRAFT,
            tags=tags or [],
            alpha_factors=alpha_factors or [],
        )
        self.db.save_hypothesis(hypothesis)
        return hypothesis

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a hypothesis by ID"""
        return self.db.get_hypothesis(hypothesis_id)

    def list(
        self,
        status: Optional[HypothesisStatus] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Hypothesis]:
        """List hypotheses with filters"""
        return self.db.list_hypotheses(status=status, tags=tags, limit=limit)

    def activate(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Transition hypothesis from DRAFT to ACTIVE"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if hyp.status != HypothesisStatus.DRAFT:
            raise ValueError(f"Cannot activate hypothesis in {hyp.status.value} status")
        hyp.status = HypothesisStatus.ACTIVE
        hyp.updated_at = datetime.now()
        self.db.save_hypothesis(hyp)
        return hyp

    def start_testing(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Transition from ACTIVE to TESTING"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if hyp.status != HypothesisStatus.ACTIVE:
            raise ValueError(f"Cannot start testing hypothesis in {hyp.status.value} status")
        hyp.status = HypothesisStatus.TESTING
        hyp.updated_at = datetime.now()
        self.db.save_hypothesis(hyp)
        return hyp

    def validate(
        self,
        hypothesis_id: str,
        evidence: Optional[List[str]] = None,
        backtest_ids: Optional[List[str]] = None,
    ) -> Optional[Hypothesis]:
        """Mark hypothesis as VALIDATED with evidence"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if hyp.status != HypothesisStatus.TESTING:
            raise ValueError(f"Cannot validate hypothesis in {hyp.status.value} status")
        hyp.status = HypothesisStatus.VALIDATED
        hyp.updated_at = datetime.now()
        if evidence:
            hyp.evidence.extend(evidence)
        if backtest_ids:
            hyp.backtest_ids.extend(backtest_ids)
        self.db.save_hypothesis(hyp)
        return hyp

    def invalidate(
        self,
        hypothesis_id: str,
        reason: str,
        evidence: Optional[List[str]] = None,
    ) -> Optional[Hypothesis]:
        """Mark hypothesis as INVALIDATED with reason"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if hyp.status in (HypothesisStatus.VALIDATED, HypothesisStatus.INVALIDATED):
            raise ValueError(f"Cannot invalidate hypothesis in {hyp.status.value} status")
        hyp.status = HypothesisStatus.INVALIDATED
        hyp.updated_at = datetime.now()
        hyp.invalidated_at = datetime.now()
        hyp.invalidation_reason = reason
        if evidence:
            hyp.evidence.extend(evidence)
        self.db.save_hypothesis(hyp)
        return hyp

    def archive(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Archive a hypothesis"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        hyp.status = HypothesisStatus.ARCHIVED
        hyp.updated_at = datetime.now()
        self.db.save_hypothesis(hyp)
        return hyp

    def delete(self, hypothesis_id: str) -> bool:
        """Delete a hypothesis"""
        return self.db.delete_hypothesis(hypothesis_id)

    def add_evidence(self, hypothesis_id: str, evidence: str) -> Optional[Hypothesis]:
        """Add evidence to a hypothesis"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        hyp.evidence.append(evidence)
        hyp.updated_at = datetime.now()
        self.db.save_hypothesis(hyp)
        return hyp

    def link_backtest(self, hypothesis_id: str, backtest_id: str) -> Optional[Hypothesis]:
        """Link a backtest result to a hypothesis"""
        hyp = self.db.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if backtest_id not in hyp.backtest_ids:
            hyp.backtest_ids.append(backtest_id)
            hyp.updated_at = datetime.now()
            self.db.save_hypothesis(hyp)
        return hyp

    def search(self, query: str) -> List[Hypothesis]:
        """Search hypotheses by title or description"""
        all_hyps = self.db.list_hypotheses(limit=1000)
        query_lower = query.lower()
        return [
            h for h in all_hyps
            if query_lower in h.title.lower() or query_lower in h.description.lower()
        ]
