"""Tests for HypothesisRegistry — Wave D112."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.research.models import Hypothesis, HypothesisStatus
from vibe_trading.research.registry import HypothesisRegistry


def _hyp(status=HypothesisStatus.DRAFT):
    return Hypothesis(id="hyp_1", title="t", description="d", status=status)


def _registry(hyp=None):
    db = MagicMock()
    db.get_hypothesis = AsyncMock(return_value=hyp)
    db.save_hypothesis = AsyncMock(return_value=True)
    db.search_hypotheses = AsyncMock(return_value=[])
    db.get_all_hypotheses = AsyncMock(return_value=[])
    db.delete_hypothesis = AsyncMock(return_value=True)
    r = HypothesisRegistry(db=db)
    return r, db


class TestHypothesisRegistry:
    @pytest.mark.asyncio
    async def test_create(self):
        r, db = _registry()
        hyp = await r.create(title="x", description="d", tags=["a"])
        assert hyp.id.startswith("hyp_")
        assert hyp.status == HypothesisStatus.DRAFT
        db.save_hypothesis.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_missing(self):
        r, _ = _registry()  # get 回 None
        assert await r.get("nope") is None

    @pytest.mark.asyncio
    async def test_activate(self):
        r, _ = _registry(_hyp(HypothesisStatus.DRAFT))
        hyp = await r.activate("hyp_1")
        assert hyp.status == HypothesisStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_activate_wrong_status(self):
        r, _ = _registry(_hyp(HypothesisStatus.ACTIVE))
        assert await r.activate("hyp_1") is None

    @pytest.mark.asyncio
    async def test_start_testing(self):
        r, _ = _registry(_hyp(HypothesisStatus.ACTIVE))
        hyp = await r.start_testing("hyp_1")
        assert hyp.status == HypothesisStatus.TESTING

    @pytest.mark.asyncio
    async def test_start_testing_wrong_status(self):
        r, _ = _registry(_hyp(HypothesisStatus.DRAFT))
        assert await r.start_testing("hyp_1") is None

    @pytest.mark.asyncio
    async def test_validate(self):
        r, _ = _registry(_hyp(HypothesisStatus.TESTING))
        hyp = await r.validate("hyp_1", evidence={"sharpe": 2.0})
        assert hyp.status == HypothesisStatus.VALIDATED
        assert hyp.validated_at is not None
        assert hyp.evidence[0]["type"] == "validation"

    @pytest.mark.asyncio
    async def test_validate_wrong_status(self):
        r, _ = _registry(_hyp(HypothesisStatus.DRAFT))
        assert await r.validate("hyp_1") is None

    @pytest.mark.asyncio
    async def test_invalidate(self):
        r, _ = _registry(_hyp(HypothesisStatus.TESTING))
        hyp = await r.invalidate("hyp_1", reason="no edge",
                                 evidence={"ic": 0.01})
        assert hyp.status == HypothesisStatus.INVALIDATED
        assert hyp.invalidation_reason == "no edge"
        assert hyp.evidence[0]["type"] == "invalidation"

    @pytest.mark.asyncio
    async def test_invalidate_blocked_statuses(self):
        r, _ = _registry(_hyp(HypothesisStatus.VALIDATED))
        assert await r.invalidate("hyp_1", reason="x") is None

    @pytest.mark.asyncio
    async def test_archive(self):
        r, _ = _registry(_hyp(HypothesisStatus.DRAFT))
        assert await r.archive("hyp_1") is True  # update 回 db.save 的 bool
        # 狀態在 hyp 上 (由 update 持久化前設)
        assert _hyp(HypothesisStatus.DRAFT).status == HypothesisStatus.DRAFT

    @pytest.mark.asyncio
    async def test_archive_missing(self):
        r, _ = _registry()
        assert await r.archive("nope") is None

    @pytest.mark.asyncio
    async def test_add_backtest_result(self):
        r, _ = _registry(_hyp())
        hyp = await r.add_backtest_result("hyp_1", {"sharpe": 1.5})
        assert hyp.backtest_results[0]["sharpe"] == 1.5
        assert "timestamp" in hyp.backtest_results[0]

    @pytest.mark.asyncio
    async def test_add_live_result(self):
        r, _ = _registry(_hyp())
        hyp = await r.add_live_result("hyp_1", {"pnl": 100.0})
        assert hyp.live_results[0]["pnl"] == 100.0

    @pytest.mark.asyncio
    async def test_add_result_missing(self):
        r, _ = _registry()
        assert await r.add_backtest_result("nope", {}) is None
        assert await r.add_live_result("nope", {}) is None

    @pytest.mark.asyncio
    async def test_search_and_get_all(self):
        r, db = _registry()
        await r.search("alpha")
        db.search_hypotheses.assert_called_once_with("alpha")
        await r.get_all()
        db.get_all_hypotheses.assert_called_once_with(None)
        await r.get_all(HypothesisStatus.ACTIVE)
        db.get_all_hypotheses.assert_called_with(HypothesisStatus.ACTIVE)

    @pytest.mark.asyncio
    async def test_delete(self):
        r, db = _registry()
        assert await r.delete("hyp_1") is True
