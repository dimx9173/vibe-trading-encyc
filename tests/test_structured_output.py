"""Tests for structured output functionality."""
import json
import pytest
from pydantic import ValidationError

from vibe_trading.agents.decision.structured_output import (
    extract_json_from_text,
    parse_structured_output,
)
from vibe_trading.agents.decision.schemas import (
    FinalDecisionSchema,
    TradingPlanSchema,
    InvestmentRecommendationSchema,
    TraderAnalysisSchema,
)


class TestExtractJsonFromText:
    """Test JSON extraction from text."""

    def test_extract_json_from_markdown_block(self):
        """Test extracting JSON from markdown code block."""
        text = """Some text before
```json
{"decision": "BUY", "confidence": 0.8, "rationale": "Test"}
```
Some text after"""
        result = extract_json_from_text(text)
        assert result is not None
        assert result["decision"] == "BUY"
        assert result["confidence"] == 0.8

    def test_extract_json_from_plain_text(self):
        """Test extracting JSON from plain text."""
        text = 'Here is the result: {"decision": "SELL", "confidence": 0.7, "rationale": "Test"}'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["decision"] == "SELL"

    def test_extract_json_no_json(self):
        """Test when no JSON is present."""
        text = "This is just plain text without any JSON"
        result = extract_json_from_text(text)
        assert result is None

    def test_extract_json_invalid_json(self):
        """Test with invalid JSON."""
        text = '{"decision": "BUY", "confidence": 0.8, "rationale":'
        result = extract_json_from_text(text)
        assert result is None


class TestParseStructuredOutput:
    """Test structured output parsing."""

    def test_parse_final_decision_valid(self):
        """Test parsing valid FinalDecisionSchema."""
        text = """
```json
{
    "decision": "BUY",
    "confidence": 0.85,
    "rationale": "Strong bullish signals",
    "execution_instructions": "Enter at market price",
    "risk_assessment": "Moderate risk"
}
```
"""
        result = parse_structured_output(text, FinalDecisionSchema)
        assert result is not None
        assert result.decision == "BUY"
        assert result.confidence == 0.85
        assert result.rationale == "Strong bullish signals"

    def test_parse_final_decision_invalid_enum(self):
        """Test parsing with invalid decision enum."""
        text = '{"decision": "INVALID", "confidence": 0.8, "rationale": "Test"}'
        result = parse_structured_output(text, FinalDecisionSchema)
        assert result is None

    def test_parse_final_decision_missing_required(self):
        """Test parsing with missing required field."""
        text = '{"decision": "BUY", "confidence": 0.8}'
        result = parse_structured_output(text, FinalDecisionSchema)
        assert result is None

    def test_parse_trader_analysis_valid(self):
        """Test parsing valid TraderAnalysisSchema."""
        text = """
{
    "plan_approved": true,
    "adjustments": "Reduce position size by 20%",
    "timing_suggestion": "Wait for pullback to support",
    "risk_warnings": ["High volatility", "Uncertain market direction"],
    "confidence": 0.75
}
"""
        result = parse_structured_output(text, TraderAnalysisSchema)
        assert result is not None
        assert result.plan_approved is True
        assert result.adjustments == "Reduce position size by 20%"
        assert len(result.risk_warnings) == 2
        assert result.confidence == 0.75

    def test_parse_investment_recommendation_valid(self):
        """Test parsing valid InvestmentRecommendationSchema."""
        text = """
{
    "action": "BUY",
    "confidence": 0.9,
    "reasoning": "Strong technical and fundamental alignment",
    "key_factors": ["Bullish divergence", "Positive funding rate"],
    "risk_warnings": ["Overbought RSI"]
}
"""
        result = parse_structured_output(text, InvestmentRecommendationSchema)
        assert result is not None
        assert result.action == "BUY"
        assert result.confidence == 0.9
        assert len(result.key_factors) == 2

    def test_parse_trading_plan_valid(self):
        """Test parsing valid TradingPlanSchema."""
        text = """
{
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "entry_orders": [
        {
            "side": "BUY",
            "quantity": 0.1,
            "order_type": "MARKET"
        }
    ],
    "stop_loss_orders": [
        {
            "side": "SELL",
            "quantity": 0.1,
            "order_type": "STOP_MARKET",
            "stop_price": 45000.0
        }
    ],
    "take_profit_orders": [
        {
            "side": "SELL",
            "quantity": 0.1,
            "order_type": "LIMIT",
            "price": 55000.0
        }
    ],
    "position_size": 0.1,
    "leverage": 5,
    "execution_style": "IMMEDIATE",
    "execution_notes": "Enter immediately",
    "confidence": 0.8,
    "rationale": "Strong bullish setup"
}
"""
        result = parse_structured_output(text, TradingPlanSchema)
        assert result is not None
        assert result.symbol == "BTCUSDT"
        assert result.direction == "LONG"
        assert len(result.entry_orders) == 1
        assert result.leverage == 5

    def test_parse_with_markdown_and_extra_text(self):
        """Test parsing JSON embedded in markdown with extra text."""
        text = """Based on my analysis, here is my decision:

```json
{
    "decision": "HOLD",
    "confidence": 0.6,
    "rationale": "Market is uncertain"
}
```

I recommend waiting for clearer signals."""
        result = parse_structured_output(text, FinalDecisionSchema)
        assert result is not None
        assert result.decision == "HOLD"
        assert result.confidence == 0.6


class TestSchemaValidation:
    """Test schema validation rules."""

    def test_final_decision_all_valid_decisions(self):
        """Test all valid decision enums."""
        valid_decisions = [
            "STRONG BUY", "BUY", "WEAK BUY",
            "HOLD",
            "WEAK SELL", "SELL", "STRONG SELL"
        ]
        for decision in valid_decisions:
            data = {
                "decision": decision,
                "confidence": 0.5,
                "rationale": "Test"
            }
            result = FinalDecisionSchema(**data)
            assert result.decision == decision

    def test_final_decision_confidence_bounds(self):
        """Test confidence must be between 0 and 1."""
        # Valid
        data = {"decision": "BUY", "confidence": 0.0, "rationale": "Test"}
        result = FinalDecisionSchema(**data)
        assert result.confidence == 0.0

        data = {"decision": "BUY", "confidence": 1.0, "rationale": "Test"}
        result = FinalDecisionSchema(**data)
        assert result.confidence == 1.0

        # Invalid
        with pytest.raises(ValidationError):
            FinalDecisionSchema(decision="BUY", confidence=-0.1, rationale="Test")

        with pytest.raises(ValidationError):
            FinalDecisionSchema(decision="BUY", confidence=1.1, rationale="Test")

    def test_trader_analysis_optional_fields(self):
        """Test TraderAnalysisSchema with optional fields."""
        data = {
            "plan_approved": False,
            "timing_suggestion": "Wait",
            "risk_warnings": [],
            "confidence": 0.5
        }
        result = TraderAnalysisSchema(**data)
        assert result.adjustments is None  # Optional field

    def test_investment_recommendation_action_enum(self):
        """Test InvestmentRecommendationSchema action enum."""
        valid_actions = ["BUY", "SELL", "HOLD"]
        for action in valid_actions:
            data = {
                "action": action,
                "confidence": 0.5,
                "reasoning": "Test"
            }
            result = InvestmentRecommendationSchema(**data)
            assert result.action == action

        # Invalid action
        with pytest.raises(ValidationError):
            InvestmentRecommendationSchema(
                action="INVALID",
                confidence=0.5,
                reasoning="Test"
            )
