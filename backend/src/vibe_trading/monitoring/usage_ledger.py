"""
Usage Ledger - LLM cost tracking and analytics.

Tracks LLM API usage including token counts, costs, and provides
aggregated summaries by agent, model, symbol, and time range.
"""
from __future__ import annotations

import aiosqlite
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)


# Model pricing per 1M tokens (USD)
MODEL_PRICING = {
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    "claude-3-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "deepseek-v3": {"input": 0.14, "output": 0.28},
    "deepseek-v2": {"input": 0.14, "output": 0.28},
}


@dataclass
class UsageEntry:
    """Single usage record."""
    id: Optional[int]
    timestamp: datetime
    agent_name: str
    model: str
    symbol: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class UsageSummary:
    """Aggregated usage summary."""
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@dataclass
class DailySummary:
    """Daily usage summary."""
    date: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@dataclass
class AgentUsage:
    """Usage summary for a specific agent."""
    agent_name: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@dataclass
class ModelUsage:
    """Usage summary for a specific model."""
    model: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class UsageLedger:
    """
    Tracks LLM API usage and costs.

    Provides methods to record usage, query summaries by various dimensions,
    and estimate costs based on model pricing.
    """

    def __init__(self, db_path: str = "vibe_trading.db"):
        """
        Initialize usage ledger.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure database table exists."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp
                ON usage_ledger(timestamp)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_agent
                ON usage_ledger(agent_name)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_model
                ON usage_ledger(model)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_symbol
                ON usage_ledger(symbol)
            """)
            await db.commit()

        self._initialized = True

    async def record_usage(
        self,
        agent_name: str,
        model: str,
        symbol: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        timestamp: Optional[datetime] = None,
    ) -> UsageEntry:
        """
        Record a single LLM usage event.

        Args:
            agent_name: Name of the agent making the request
            model: LLM model used
            symbol: Trading symbol context
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_usd: Cost in USD
            timestamp: Optional timestamp (defaults to now)

        Returns:
            UsageEntry with the recorded data
        """
        await self._ensure_initialized()

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO usage_ledger
                (timestamp, agent_name, model, symbol, input_tokens, output_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp.isoformat(),
                    agent_name,
                    model,
                    symbol,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                ),
            )
            await db.commit()
            entry_id = cursor.lastrowid

        return UsageEntry(
            id=entry_id,
            timestamp=timestamp,
            agent_name=agent_name,
            model=model,
            symbol=symbol,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    async def get_summary(
        self,
        agent_name: Optional[str] = None,
        model: Optional[str] = None,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> UsageSummary:
        """
        Get aggregated usage summary.

        Args:
            agent_name: Filter by agent name
            model: Filter by model
            symbol: Filter by symbol
            start_time: Filter by start time
            end_time: Filter by end time

        Returns:
            UsageSummary with aggregated data
        """
        await self._ensure_initialized()

        conditions = []
        params = []

        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd
            FROM usage_ledger
            WHERE {where_clause}
        """

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()

            if row:
                return UsageSummary(
                    total_requests=row["total_requests"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                    total_cost_usd=row["total_cost_usd"],
                )

        return UsageSummary(
            total_requests=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
        )

    async def get_daily_summary(self, days: int = 7) -> List[DailySummary]:
        """
        Get daily usage summaries for the past N days.

        Args:
            days: Number of days to include

        Returns:
            List of DailySummary, most recent first
        """
        await self._ensure_initialized()

        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        query = """
            SELECT
                DATE(timestamp) as date,
                COUNT(*) as total_requests,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd
            FROM usage_ledger
            WHERE timestamp >= ?
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, (start_date,))
            rows = await cursor.fetchall()

            return [
                DailySummary(
                    date=row["date"],
                    total_requests=row["total_requests"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                    total_cost_usd=row["total_cost_usd"],
                )
                for row in rows
            ]

    async def get_top_agents(self, limit: int = 5) -> List[AgentUsage]:
        """
        Get top agents by usage.

        Args:
            limit: Maximum number of agents to return

        Returns:
            List of AgentUsage, sorted by total requests descending
        """
        await self._ensure_initialized()

        query = """
            SELECT
                agent_name,
                COUNT(*) as total_requests,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd
            FROM usage_ledger
            GROUP BY agent_name
            ORDER BY total_requests DESC
            LIMIT ?
        """

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, (limit,))
            rows = await cursor.fetchall()

            return [
                AgentUsage(
                    agent_name=row["agent_name"],
                    total_requests=row["total_requests"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                    total_cost_usd=row["total_cost_usd"],
                )
                for row in rows
            ]

    async def get_top_models(self, limit: int = 5) -> List[ModelUsage]:
        """
        Get top models by usage.

        Args:
            limit: Maximum number of models to return

        Returns:
            List of ModelUsage, sorted by total requests descending
        """
        await self._ensure_initialized()

        query = """
            SELECT
                model,
                COUNT(*) as total_requests,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd
            FROM usage_ledger
            GROUP BY model
            ORDER BY total_requests DESC
            LIMIT ?
        """

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, (limit,))
            rows = await cursor.fetchall()

            return [
                ModelUsage(
                    model=row["model"],
                    total_requests=row["total_requests"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                    total_cost_usd=row["total_cost_usd"],
                )
                for row in rows
            ]

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Estimate cost for a given model and token counts.

        Args:
            model: LLM model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Estimated cost in USD
        """
        pricing = MODEL_PRICING.get(model)
        if not pricing:
            return 0.0

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost


# Global singleton instance
_usage_ledger: Optional[UsageLedger] = None


def get_usage_ledger() -> UsageLedger:
    """
    Get the global usage ledger instance.

    Returns:
        UsageLedger singleton
    """
    global _usage_ledger
    if _usage_ledger is None:
        _usage_ledger = UsageLedger()
    return _usage_ledger
