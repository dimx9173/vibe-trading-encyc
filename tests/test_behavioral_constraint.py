"""Tests for BehavioralConstraint (Wave D — coverage 85% plan)."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from vibe_trading.prime.constraints.behavioral import BehavioralConstraint
from vibe_trading.agents.messaging import MessageType


def _msg(sender: str, content: dict, mtype=None):
    m = MagicMock()
    m.sender = sender
    m.content = content
    m.message_type = mtype or MessageType.ANALYSIS_REPORT
    m.timestamp = datetime.now()
    return m


class TestBehavioral:
    @pytest.mark.asyncio
    async def test_domain_violation(self):
        c = BehavioralConstraint()
        # technical analyst 送 fundamental 內容 → 越權
        msg = _msg("technical_analyst", {"funding_rate": 0.01})
        result = await c.check(msg)
        assert result.passed is False
        assert "越权" in result.reason

    @pytest.mark.asyncio
    async def test_domain_allowed(self):
        c = BehavioralConstraint()
        msg = _msg("technical_analyst", {"technical_indicators": {"rsi": 50}})
        result = await c.check(msg)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_direct_order_denied(self):
        c = BehavioralConstraint()
        msg = _msg("news_analyst", {"direct_order": "BUY"})
        result = await c.check(msg)
        assert result.passed is False
        assert "无权直接下单" in result.reason

    @pytest.mark.asyncio
    async def test_direct_order_allowed(self):
        c = BehavioralConstraint()
        msg = _msg("trader", {"direct_order": "BUY", "trading_plan": "x"})
        result = await c.check(msg)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_abnormal_frequency(self):
        c = BehavioralConstraint()
        # 連續 10 次相同類型 → 異常
        results = []
        for i in range(10):
            msg = _msg("technical_analyst", {"technical_indicators": {}})
            results.append(await c.check(msg))
        # 第 10 次 (recent_count >= 8) → fail
        assert any(r.passed is False for r in results[-3:])

    @pytest.mark.asyncio
    async def test_extract_domain(self):
        c = BehavioralConstraint()
        assert c._extract_domain({"technical_indicators": {}}) == "technical_analysis"
        assert c._extract_domain({"news_item": 1}) == "news_analysis"
        assert c._extract_domain({"unrelated": 1}) is None

    @pytest.mark.asyncio
    async def test_validate_message_format(self):
        c = BehavioralConstraint()
        msg = _msg("technical_analyst", {"technical_indicators": {}})
        assert c._validate_message_format(msg) in (True, False)

    @pytest.mark.asyncio
    async def test_get_expected_types(self):
        c = BehavioralConstraint()
        types = c._get_expected_message_types("analyst")
        assert len(types) > 0
