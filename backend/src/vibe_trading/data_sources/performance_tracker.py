"""
Performance Tracker

Tracks per-trade performance and computes live metrics:
- Sharpe ratio, Max Drawdown, Win Rate
- SQLite persistence for cross-session evaluation
- Query interface for EvidenceGate / reporting

Part of the external data layer Phase 4 (Task 4.2).
"""
import sqlite3
import math
from datetime import datetime
from typing import Any, Dict, List, Optional


class TradeRecord:
    """A single closed trade record"""

    def __init__(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        closed_at: Optional[datetime] = None,
        leverage: int = 5,
    ):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.realized_pnl = realized_pnl
        self.closed_at = closed_at or datetime.now()
        self.leverage = leverage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "closed_at": self.closed_at.isoformat(),
            "leverage": self.leverage,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeRecord":
        return cls(
            symbol=data["symbol"],
            side=data["side"],
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            exit_price=data["exit_price"],
            realized_pnl=data["realized_pnl"],
            closed_at=datetime.fromisoformat(data["closed_at"]),
            leverage=data.get("leverage", 5),
        )


class PerformanceTracker:
    """Track closed trades and compute performance metrics"""

    def __init__(self, db_path: str = "performance.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    closed_at TEXT NOT NULL,
                    leverage INTEGER NOT NULL DEFAULT 5
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at)")
            conn.commit()

    def record_trade(self, trade: TradeRecord) -> bool:
        """Record a closed trade"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trades
                (symbol, side, quantity, entry_price, exit_price,
                 realized_pnl, closed_at, leverage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.realized_pnl,
                trade.closed_at.isoformat(),
                trade.leverage,
            ))
            conn.commit()
        return True

    def get_trades(self, limit: Optional[int] = None) -> List[TradeRecord]:
        """Get all recorded trades, newest first"""
        query = "SELECT * FROM trades ORDER BY closed_at DESC"
        params = []
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            TradeRecord(
                symbol=r[1],
                side=r[2],
                quantity=r[3],
                entry_price=r[4],
                exit_price=r[5],
                realized_pnl=r[6],
                closed_at=datetime.fromisoformat(r[7]),
                leverage=r[8],
            )
            for r in rows
        ]

    def get_trades_since(self, since: datetime) -> List[TradeRecord]:
        """Get trades closed since a given time"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE closed_at >= ? ORDER BY closed_at ASC",
                (since.isoformat(),),
            )
            rows = cursor.fetchall()

        return [
            TradeRecord(
                symbol=r[1],
                side=r[2],
                quantity=r[3],
                entry_price=r[4],
                exit_price=r[5],
                realized_pnl=r[6],
                closed_at=datetime.fromisoformat(r[7]),
                leverage=r[8],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Metrics (computed from recorded trades)
    # ------------------------------------------------------------------

    def win_rate(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Fraction of profitable trades (0-1)"""
        trades = trades if trades is not None else self.get_trades()
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.realized_pnl > 0)
        return wins / len(trades)

    def total_pnl(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Sum of realized PnL"""
        trades = trades if trades is not None else self.get_trades()
        return sum(t.realized_pnl for t in trades)

    def profit_factor(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Gross profit / gross loss (0 if no losses)"""
        trades = trades if trades is not None else self.get_trades()
        gross_profit = sum(t.realized_pnl for t in trades if t.realized_pnl > 0)
        gross_loss = abs(sum(t.realized_pnl for t in trades if t.realized_pnl < 0))
        if gross_loss == 0:
            return 0.0
        return gross_profit / gross_loss

    def sharpe_ratio(
        self,
        trades: Optional[List[TradeRecord]] = None,
        risk_free_rate: float = 0.0,
    ) -> float:
        """Sharpe ratio of per-trade returns (PnL / notional), scale-free.

        Each trade's return is ``realized_pnl / (quantity * entry_price)`` so
        the metric reflects trade quality, not position size. Zero-notional
        trades are skipped; <2 valid trades yields 0.0.
        """
        trades = trades if trades is not None else self.get_trades()

        returns = []
        for t in trades:
            notional = t.quantity * t.entry_price
            if notional > 0:
                returns.append(t.realized_pnl / notional)
        if len(returns) < 2:
            return 0.0

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)

        if variance == 0:
            return 0.0

        std = math.sqrt(variance)
        return (mean - risk_free_rate) / std

    def max_drawdown(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Max drawdown of the cumulative PnL curve as a ratio (0..1+).

        Standard definition: per-point ``(peak - cumulative) / peak`` of the
        cumulative PnL curve, maximised over time. Trades are sorted
        chronologically regardless of input order, so DB (DESC) and explicit
        (ASC) inputs yield identical results. Ratio can exceed 1.0 when
        cumulative PnL goes negative.
        """
        trades = trades if trades is not None else self.get_trades()
        if not trades:
            return 0.0

        ordered = sorted(trades, key=lambda t: t.closed_at)

        peak = 0.0
        cumulative = 0.0
        max_dd = 0.0

        for t in ordered:
            cumulative += t.realized_pnl
            if cumulative > peak:
                peak = cumulative
            if peak > 0:
                max_dd = max(max_dd, (peak - cumulative) / peak)

        return max_dd

    def get_metrics(
        self,
        trades: Optional[List[TradeRecord]] = None,
    ) -> Dict[str, float]:
        """Compute all performance metrics at once"""
        trades = trades if trades is not None else self.get_trades()
        return {
            "total_pnl": self.total_pnl(trades),
            "win_rate": self.win_rate(trades),
            "profit_factor": self.profit_factor(trades),
            "sharpe_ratio": self.sharpe_ratio(trades),
            "max_drawdown": self.max_drawdown(trades),
            "trade_count": len(trades),
        }

    def clear(self) -> None:
        """Delete all trade records"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM trades")
            conn.commit()
