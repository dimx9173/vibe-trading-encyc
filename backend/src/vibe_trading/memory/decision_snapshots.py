"""
决策级反思快照存储（P0.1 C4）。

为每一个决策（包括 HOLD/弱信号）记录快照，在 N 根 bar 后回看：
若当时 HOLD 而行情大涨（或做多后大跌），则生成反思写入记忆。
这补齐了"只反思已平仓交易"的盲区——多数决策其实是 HOLD。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DecisionSnapshot:
    """单条决策快照。"""
    decision_id: str
    symbol: str
    decision: str  # BUY/SELL/HOLD/WEAK_BUY/...
    price_at_decision: float
    bar_open_time_ms: int
    confidence: float = 0.0
    context_digest: str = ""
    recorded_at: float = 0.0


class DecisionSnapshotStore:
    """
    内存中的待评估决策快照队列。

    成熟的快照（bar_open_time_ms 距当前已超过 maturation 窗口）会被弹出并交给
    反思器评估。注意：成熟反思写入 PersistentMemory（持久化），而未成熟的快照
    仅存活于当前会话（重启会丢弃，窗口通常较短，可接受）。
    """

    def __init__(self) -> None:
        self._snapshots: List[DecisionSnapshot] = []

    def record(self, snapshot: DecisionSnapshot) -> None:
        self._snapshots.append(snapshot)

    def pop_matured(
        self,
        current_bar_open_time_ms: Optional[int],
        maturation_window_ms: int,
    ) -> List[DecisionSnapshot]:
        """弹出已超过成熟窗口的快照，保留尚未成熟的。"""
        if current_bar_open_time_ms is None:
            return []

        matured: List[DecisionSnapshot] = []
        pending: List[DecisionSnapshot] = []
        for snap in self._snapshots:
            elapsed = current_bar_open_time_ms - snap.bar_open_time_ms
            if elapsed >= maturation_window_ms:
                matured.append(snap)
            else:
                pending.append(snap)
        self._snapshots = pending
        return matured

    def __len__(self) -> int:
        return len(self._snapshots)


def interval_to_ms(interval: str) -> int:
    """K线间隔 -> 毫秒（'30m'/'1h'/'5m'/'4h'/'1d'/'1w'）。"""
    interval = (interval or "").strip().lower()
    if not interval:
        return 0
    unit = interval[-1]
    try:
        amount = int(interval[:-1])
    except ValueError:
        return 0
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    return amount * multipliers.get(unit, 0)
