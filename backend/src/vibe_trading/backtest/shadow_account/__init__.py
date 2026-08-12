"""Shadow Account - 行為診斷系統

分析真實交易記錄，診斷行為偏差，生成改進建議。
"""
from .models import (
    TradeRecord,
    BehavioralProfile,
    BiasScore,
    ExtractedRule,
    CounterfactualResult,
    ShadowReport,
)
from .parser import parse_binance_csv, pair_trades
from .biases import calculate_all_biases
from .rules import extract_rules
from .counterfactual import run_counterfactual
from .report import generate_html_report
from .analyzer import ShadowAccountAnalyzer

__all__ = [
    "TradeRecord",
    "BehavioralProfile",
    "BiasScore",
    "ExtractedRule",
    "CounterfactualResult",
    "ShadowReport",
    "parse_binance_csv",
    "calculate_all_biases",
    "extract_rules",
    "run_counterfactual",
    "generate_html_report",
    "ShadowAccountAnalyzer",
]
