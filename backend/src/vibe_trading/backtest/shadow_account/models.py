"""Shadow Account 資料模型"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class BiasType(str, Enum):
    """行為偏差類型"""
    DISPOSITION = "disposition"  # 處置效應
    OVERTRADING = "overtrading"  # 過度交易
    CHASING = "chasing"  # 追漲殺跌
    ANCHORING = "anchoring"  # 錨定效應
    GAMBLER = "gambler"  # 賭徒謬誤


@dataclass
class TradeRecord:
    """單一交易記錄"""
    trade_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    fee: float = 0.0
    is_closed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BiasScore:
    """單一偏差分數"""
    bias_type: BiasType
    score: float  # 0.0 - 1.0, 越高越嚴重
    description: str
    evidence: List[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class BehavioralProfile:
    """行為剖面"""
    trader_id: str
    analysis_period_start: datetime
    analysis_period_end: datetime
    total_trades: int
    closed_trades: int
    open_trades: int
    biases: List[BiasScore] = field(default_factory=list)
    overall_score: float = 0.0  # 0.0 - 1.0
    summary: str = ""

    @property
    def bias_dict(self) -> Dict[BiasType, BiasScore]:
        return {b.bias_type: b for b in self.biases}


@dataclass
class ExtractedRule:
    """提取的行為規則"""
    rule_id: str
    description: str
    trigger_condition: str
    suggested_action: str
    confidence: float  # 0.0 - 1.0
    evidence_count: int


@dataclass
class CounterfactualResult:
    """反事實回測結果"""
    actual_pnl: float
    actual_pnl_pct: float
    ideal_pnl: float
    ideal_pnl_pct: float
    improvement: float  # ideal - actual
    improvement_pct: float
    actual_trades: int
    ideal_trades: int
    actual_win_rate: float
    ideal_win_rate: float
    actual_sharpe: float
    ideal_sharpe: float
    equity_curve_actual: List[float] = field(default_factory=list)
    equity_curve_ideal: List[float] = field(default_factory=list)


@dataclass
class ShadowReport:
    """Shadow Account 報告"""
    trader_id: str
    generated_at: datetime
    profile: BehavioralProfile
    rules: List[ExtractedRule]
    counterfactual: Optional[CounterfactualResult]
    recommendations: List[str] = field(default_factory=list)
    html_content: str = ""
