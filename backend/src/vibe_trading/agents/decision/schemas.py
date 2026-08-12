"""
Pydantic schemas for structured LLM output.

These schemas enforce structured output from Trader/PM/ResearchManager,
eliminating fragile text parsing.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class OrderSchema(BaseModel):
    """Schema for entry/exit orders."""
    side: Literal["BUY", "SELL"] = Field(description="Order side")
    quantity: float = Field(gt=0, description="Order quantity")
    order_type: Literal["MARKET", "LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"] = Field(
        description="Order type"
    )
    price: Optional[float] = Field(None, description="Limit price (for LIMIT orders)")
    stop_price: Optional[float] = Field(None, description="Stop price (for STOP/TP orders)")


class TradingPlanSchema(BaseModel):
    """Structured output schema for TraderAgent."""
    symbol: str = Field(description="Trading symbol, e.g., BTCUSDT")
    direction: Literal["LONG", "SHORT", "NEUTRAL"] = Field(description="Trade direction")
    entry_orders: List[OrderSchema] = Field(default_factory=list, description="Entry orders")
    stop_loss_orders: List[OrderSchema] = Field(default_factory=list, description="Stop loss orders")
    take_profit_orders: List[OrderSchema] = Field(default_factory=list, description="Take profit orders")
    position_size: float = Field(ge=0, description="Position size in base currency")
    leverage: int = Field(ge=1, le=125, description="Leverage multiplier")
    execution_style: Literal["IMMEDIATE", "TWAP", "PULLBACK"] = Field(
        description="Execution style"
    )
    execution_notes: str = Field(default="", description="Execution notes")
    confidence: float = Field(ge=0, le=1, description="Confidence level 0-1")
    rationale: str = Field(description="Trading rationale")


class FinalDecisionSchema(BaseModel):
    """Structured output schema for PortfolioManagerAgent."""
    decision: Literal[
        "STRONG BUY", "BUY", "WEAK BUY",
        "HOLD",
        "WEAK SELL", "SELL", "STRONG SELL"
    ] = Field(description="Final trading decision")
    confidence: float = Field(ge=0, le=1, description="Decision confidence 0-1")
    rationale: str = Field(description="Decision rationale")
    execution_instructions: Optional[str] = Field(
        None, description="Specific execution instructions"
    )
    risk_assessment: str = Field(
        default="", description="Risk assessment summary"
    )


class InvestmentRecommendationSchema(BaseModel):
    """Structured output schema for ResearchManagerAgent."""
    action: Literal["BUY", "SELL", "HOLD"] = Field(
        description="Recommended action"
    )
    confidence: float = Field(ge=0, le=1, description="Recommendation confidence 0-1")
    reasoning: str = Field(description="Reasoning for recommendation")
    key_factors: List[str] = Field(
        default_factory=list, description="Key factors influencing decision"
    )
    risk_warnings: List[str] = Field(
        default_factory=list, description="Risk warnings"
    )
class TraderAnalysisSchema(BaseModel):
    """Structured output schema for TraderAgent analysis."""
    plan_approved: bool = Field(description="Whether the quantitative plan is approved")
    adjustments: Optional[str] = Field(None, description="Adjustment notes or null")
    timing_suggestion: str = Field(description="Execution timing suggestion")
    risk_warnings: List[str] = Field(default_factory=list, description="Risk warnings")
    confidence: float = Field(ge=0, le=1, description="Confidence level 0-1")
