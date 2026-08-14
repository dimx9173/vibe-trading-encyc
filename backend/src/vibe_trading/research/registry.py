"""
Hypothesis Registry

Manages the lifecycle of trading hypotheses:
- Create, update, search, invalidate, archive
- Link to backtest results
- Track evidence and validation status
"""
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from .models import Hypothesis, HypothesisStatus
from .database import ResearchDatabase


class HypothesisRegistry:
    """Hypothesis lifecycle manager"""
    
    def __init__(self, db: Optional[ResearchDatabase] = None):
        self.db = db or ResearchDatabase()
    
    async def create(
        self,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        author: str = ""
    ) -> Hypothesis:
        """Create a new hypothesis in DRAFT status"""
        hypothesis = Hypothesis(
            id=f"hyp_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            status=HypothesisStatus.DRAFT,
            tags=tags or [],
            author=author,
        )
        
        await self.db.save_hypothesis(hypothesis)
        return hypothesis
    
    async def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a hypothesis by ID"""
        return await self.db.get_hypothesis(hypothesis_id)
    
    async def update(self, hypothesis: Hypothesis) -> bool:
        """Update a hypothesis"""
        hypothesis.updated_at = datetime.now()
        return await self.db.save_hypothesis(hypothesis)
    
    async def activate(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Transition from DRAFT to ACTIVE"""
        hyp = await self.get(hypothesis_id)
        if not hyp or hyp.status != HypothesisStatus.DRAFT:
            return None
        
        hyp.status = HypothesisStatus.ACTIVE
        await self.update(hyp)
        return hyp
    
    async def start_testing(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Transition from ACTIVE to TESTING"""
        hyp = await self.get(hypothesis_id)
        if not hyp or hyp.status != HypothesisStatus.ACTIVE:
            return None
        
        hyp.status = HypothesisStatus.TESTING
        await self.update(hyp)
        return hyp
    
    async def validate(
        self,
        hypothesis_id: str,
        evidence: Optional[Dict[str, Any]] = None
    ) -> Optional[Hypothesis]:
        """Mark hypothesis as VALIDATED"""
        hyp = await self.get(hypothesis_id)
        if not hyp or hyp.status != HypothesisStatus.TESTING:
            return None
        
        hyp.status = HypothesisStatus.VALIDATED
        hyp.validated_at = datetime.now()
        
        if evidence:
            hyp.evidence.append({
                **evidence,
                "timestamp": datetime.now().isoformat(),
                "type": "validation",
            })
        
        await self.update(hyp)
        return hyp
    
    async def invalidate(
        self,
        hypothesis_id: str,
        reason: str,
        evidence: Optional[Dict[str, Any]] = None
    ) -> Optional[Hypothesis]:
        """Mark hypothesis as INVALIDATED"""
        hyp = await self.get(hypothesis_id)
        if not hyp or hyp.status in (HypothesisStatus.VALIDATED, HypothesisStatus.INVALIDATED):
            return None
        
        hyp.status = HypothesisStatus.INVALIDATED
        hyp.invalidated_at = datetime.now()
        hyp.invalidation_reason = reason
        
        if evidence:
            hyp.evidence.append({
                **evidence,
                "timestamp": datetime.now().isoformat(),
                "type": "invalidation",
            })
        
        await self.update(hyp)
        return hyp
    
    async def archive(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Archive a hypothesis"""
        hyp = await self.get(hypothesis_id)
        if not hyp:
            return None
        
        hyp.status = HypothesisStatus.ARCHIVED
        return await self.update(hyp)
    
    async def add_backtest_result(
        self,
        hypothesis_id: str,
        result: Dict[str, Any]
    ) -> Optional[Hypothesis]:
        """Add backtest result to hypothesis"""
        hyp = await self.get(hypothesis_id)
        if not hyp:
            return None
        
        hyp.backtest_results.append({
            **result,
            "timestamp": datetime.now().isoformat(),
        })
        hyp.updated_at = datetime.now()
        
        await self.db.save_hypothesis(hyp)
        return hyp
    
    async def add_live_result(
        self,
        hypothesis_id: str,
        result: Dict[str, Any]
    ) -> Optional[Hypothesis]:
        """Add live trading result to hypothesis"""
        hyp = await self.get(hypothesis_id)
        if not hyp:
            return None
        
        hyp.live_results.append({
            **result,
            "timestamp": datetime.now().isoformat(),
        })
        hyp.updated_at = datetime.now()
        
        await self.db.save_hypothesis(hyp)
        return hyp
    
    async def search(self, query: str) -> List[Hypothesis]:
        """Search hypotheses by title, description, or tags"""
        return await self.db.search_hypotheses(query)
    
    async def get_all(
        self,
        status: Optional[HypothesisStatus] = None
    ) -> List[Hypothesis]:
        """Get all hypotheses, optionally filtered by status"""
        return await self.db.get_all_hypotheses(status)
    
    async def delete(self, hypothesis_id: str) -> bool:
        """Delete a hypothesis"""
        return await self.db.delete_hypothesis(hypothesis_id)
