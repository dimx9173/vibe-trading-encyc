"""
Evidence Gate

Evaluates Paper-trading performance before allowing Live mode:
- Computes Sharpe / Max DD / Win Rate over an evaluation window
- Semi-automatic decision: system recommendation + human confirmation
- SQLite persistence of evaluation history

Part of the external data layer Phase 4 (Task 4.1).
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .performance_tracker import PerformanceTracker, TradeRecord


class EvidenceGateConfig:
    """Evidence gate thresholds"""

    def __init__(
        self,
        min_sharpe: float = 0.8,
        max_drawdown: float = 0.2,
        min_win_rate: float = 0.0,
        min_trades: int = 5,
    ):
        self.min_sharpe = min_sharpe
        self.max_drawdown = max_drawdown
        self.min_win_rate = min_win_rate
        self.min_trades = min_trades


class EvidenceGateResult:
    """Result of a paper-performance evaluation"""

    def __init__(
        self,
        passed: bool,
        sharpe_ratio: float,
        max_drawdown: float,
        win_rate: float,
        trade_count: int,
        recommendation: str,
        evaluated_at: Optional[datetime] = None,
    ):
        self.passed = passed
        self.sharpe_ratio = sharpe_ratio
        self.max_drawdown = max_drawdown
        self.win_rate = win_rate
        self.trade_count = trade_count
        self.recommendation = recommendation
        self.evaluated_at = evaluated_at or datetime.now()

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "trade_count": self.trade_count,
            "recommendation": self.recommendation,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class EvidenceGate:
    """Gate Paper→Live configuration on measured performance"""

    def __init__(
        self,
        tracker: Optional[PerformanceTracker] = None,
        config: Optional[EvidenceGateConfig] = None,
        db_path: str = "evidence_gate.db",
    ):
        self.tracker = tracker if tracker is not None else PerformanceTracker()
        self.config = config if config is not None else EvidenceGateConfig()
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize evaluation history table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    passed INTEGER NOT NULL,
                    sharpe_ratio REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    trade_count INTEGER NOT NULL,
                    recommendation TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_paper_performance(
        self,
        period_days: int = 14,
        trades: Optional[List[TradeRecord]] = None,
    ) -> EvidenceGateResult:
        """
        Evaluate Paper performance over the window and record the decision.

        Args:
            period_days: evaluation window in days (default 14)
            trades: optional explicit trade list; defaults to trades
                    recorded in the last `period_days` days

        Returns:
            EvidenceGateResult with pass/fail + recommendation
        """
        if trades is None:
            since = datetime.now() - timedelta(days=period_days)
            trades = self.tracker.get_trades_since(since)

        metrics = self.tracker.get_metrics(trades)
        sharpe = metrics["sharpe_ratio"]
        max_dd = metrics["max_drawdown"]
        win_rate = metrics["win_rate"]
        trade_count = int(metrics["trade_count"])

        passed = (
            trade_count >= self.config.min_trades
            and sharpe >= self.config.min_sharpe
            and max_dd <= self.config.max_drawdown
            and win_rate >= self.config.min_win_rate
        )

        recommendation = self._generate_recommendation(
            passed, sharpe, max_dd, win_rate, trade_count
        )

        result = EvidenceGateResult(
            passed=passed,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            trade_count=trade_count,
            recommendation=recommendation,
        )

        self._record_evaluation(result)
        return result

    def _generate_recommendation(
        self,
        passed: bool,
        sharpe: float,
        max_dd: float,
        win_rate: float,
        trade_count: int,
    ) -> str:
        """Generate a human-readable recommendation"""
        if passed:
            return (
                f"Paper 績效良好（Sharpe: {sharpe:.2f} ≥ {self.config.min_sharpe}, "
                f"Max DD: {max_dd:.2%} ≤ {self.config.max_drawdown:.0%}, "
                f"Win Rate: {win_rate:.0%}, trades: {trade_count}）。"
                f"建議切換到 Live mode（需人工確認）。"
            )
        else:
            reasons = []
            if trade_count < self.config.min_trades:
                reasons.append(f"樣本不足（{trade_count} < {self.config.min_trades} trades）")
            if sharpe < self.config.min_sharpe:
                reasons.append(f"Sharpe 過低（{sharpe:.2f} < {self.config.min_sharpe}）")
            if max_dd > self.config.max_drawdown:
                reasons.append(f"Max DD 過高（{max_dd:.2%} > {self.config.max_drawdown:.0%}）")
            if win_rate < self.config.min_win_rate:
                reasons.append(f"Win Rate 過低（{win_rate:.0%} < {self.config.min_win_rate:.0%}）")
            return (
                f"Paper 績效未達標（{'; '.join(reasons)}）。"
                f"建議繼續 Paper mode 或調整策略。"
            )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _record_evaluation(self, result: EvidenceGateResult) -> None:
        """Persist an evaluation record"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO evaluations
                (passed, sharpe_ratio, max_drawdown, win_rate,
                 trade_count, recommendation, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                int(result.passed),
                result.sharpe_ratio,
                result.max_drawdown,
                result.win_rate,
                result.trade_count,
                result.recommendation,
                result.evaluated_at.isoformat(),
            ))
            conn.commit()

    def get_evaluations(self, limit: Optional[int] = None) -> List[Dict[str, object]]:
        """Get evaluation history, newest first"""
        query = "SELECT * FROM evaluations ORDER BY evaluated_at DESC"
        params = []
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            {
                "id": r[0],
                "passed": bool(r[1]),
                "sharpe_ratio": r[2],
                "max_drawdown": r[3],
                "win_rate": r[4],
                "trade_count": r[5],
                "recommendation": r[6],
                "evaluated_at": r[7],
            }
            for r in rows
        ]

    def latest_evaluation(self) -> Optional[Dict[str, object]]:
        """Get the most recent evaluation, or None"""
        evals = self.get_evaluations(limit=1)
        return evals[0] if evals else None
