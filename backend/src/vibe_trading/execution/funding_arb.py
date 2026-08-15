"""跨所資金費率套利偵測 (Phase 4.1, Delta-Neutral).

比較各所永續資金費率, 配對出 delta-neutral 套利機會:
long 高費率所 (收費) + short 低費率所 (付費).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from vibe_trading.execution.broker_connector import BrokerType

# 8h 結算 → 每日 3 次 → 年化 3*365
_FUNDING_PERIODS_PER_DAY = 3
_DAYS_PER_YEAR = 365


@dataclass
class FundingArbOpportunity:
    """資金費率套利機會."""
    long_broker: BrokerType
    short_broker: BrokerType
    symbol: str
    annualized_rate: float  # 年化收益 (long 收 - short 付)
    spread_bps: float  # 8h 費率差 (bp)


def scan_funding_arb(
    rates: Dict[BrokerType, float],
    symbol: str = "",
    min_annualized: float = 0.10,
) -> List[FundingArbOpportunity]:
    """掃描跨所資金費率套利機會.

    Args:
        rates: {broker: 8h 資金費率 (小數, 如 0.0001 = 1bp)}
        symbol: 標的 (追蹤用)
        min_annualized: 最低年化率閾值 (預設 10%)

    Returns: 按年化率降序排列的機會清單.
    """
    opps: List[FundingArbOpportunity] = []
    brokers = list(rates)
    for i, lb in enumerate(brokers):
        for j, sb in enumerate(brokers):
            if i == j:
                continue
            spread = rates[lb] - rates[sb]
            annualized = spread * _FUNDING_PERIODS_PER_DAY * _DAYS_PER_YEAR
            if annualized >= min_annualized:
                opps.append(FundingArbOpportunity(
                    long_broker=lb, short_broker=sb, symbol=symbol,
                    annualized_rate=annualized,
                    spread_bps=spread * 10000,
                ))
    return sorted(opps, key=lambda o: -o.annualized_rate)
