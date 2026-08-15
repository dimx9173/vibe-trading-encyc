"""Tests for EmergencyRiskAgent parse + liquidation (Wave D — coverage 85% plan)."""
import pytest


from vibe_trading.agents.risk_mgmt.emergency_agent import EmergencyRiskAgent
from vibe_trading.triggers.base_trigger import (
    TriggerEvent,
    TriggerSeverity,
)


def _agent():
    return EmergencyRiskAgent(config=None)


def _event(severity=TriggerSeverity.HIGH):
    return TriggerEvent(
        event_id="e1", trigger_name="crash", severity=severity,
        data={}, timestamp=1, symbol="BTCUSDT",
    )


class TestParseAssessment:
    def test_full_parse(self):
        a = _agent()
        response = """ACTION: CLOSE_POSITION
SHOULD_ACT: true
URGENCY: HIGH
CONFIDENCE: 0.85
RATIONALE: 價格暴跌"""
        result = a._parse_assessment(response, _event())
        assert result.should_act is True
        assert result.action_type == "CLOSE_POSITION"
        assert result.urgency == "HIGH"
        assert result.confidence == 0.85

    def test_defaults(self):
        a = _agent()
        result = a._parse_assessment("nothing here", _event())
        assert result.should_act is False
        assert result.action_type == "MANUAL"
        assert result.confidence == 0.5

    def test_should_act_no(self):
        a = _agent()
        result = a._parse_assessment("SHOULD_ACT: no", _event())
        assert result.should_act is False

    def test_critical_forces_action(self):
        a = _agent()
        result = a._parse_assessment("SHOULD_ACT: no", _event(TriggerSeverity.CRITICAL))
        assert result.should_act is True
        assert result.urgency == "IMMEDIATE"
        assert result.action_type == "CLOSE_POSITION"

    def test_invalid_confidence(self):
        a = _agent()
        result = a._parse_assessment("CONFIDENCE: abc", _event())
        assert result.confidence == 0.5


class TestLiquidationRisk:
    @pytest.mark.asyncio
    async def test_high_risk_position(self):
        a = _agent()
        positions = [{
            "symbol": "BTCUSDT", "liquidation_price": 49000.0, "side": "LONG",
        }]
        prices = {"BTCUSDT": 50000.0}  # 距離 2% < 10%
        result = await a.assess_liquidation_risk(positions, prices)
        assert result.should_act is True
        assert result.action_type == "CLOSE_POSITION"
        assert "BTCUSDT" in result.recommended_action["positions_to_close"]

    @pytest.mark.asyncio
    async def test_safe_position(self):
        a = _agent()
        positions = [{
            "symbol": "BTCUSDT", "liquidation_price": 30000.0, "side": "LONG",
        }]
        prices = {"BTCUSDT": 50000.0}  # 距離 40%
        result = await a.assess_liquidation_risk(positions, prices)
        assert result.should_act is False

    @pytest.mark.asyncio
    async def test_invalid_positions_skipped(self):
        a = _agent()
        positions = [
            {"symbol": "A", "liquidation_price": 0, "side": "LONG"},  # 無效
            {"symbol": "B", "liquidation_price": 550.0, "side": "SHORT"},
        ]
        prices = {"B": 500.0}  # SHORT: (550-500)/500 = 10% → 非 <10%
        result = await a.assess_liquidation_risk(positions, prices)
        assert result.should_act is False

    @pytest.mark.asyncio
    async def test_no_positions(self):
        a = _agent()
        result = await a.assess_liquidation_risk([], {})
        assert result.should_act is False
