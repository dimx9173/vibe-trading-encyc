"""Per-bar decision journal persistence for web tracing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from vibe_trading.config.settings import get_settings


# === Singleton accessor ===
# Both QualityTracker and the web server share this so a single DB file is
# updated regardless of which path triggered the write.
_journal_storage: Optional["DecisionJournalStorage"] = None


def get_journal_storage() -> "DecisionJournalStorage":
    """Return the process-wide DecisionJournalStorage singleton."""
    global _journal_storage
    if _journal_storage is None:
        _journal_storage = DecisionJournalStorage()
    return _journal_storage


def reset_journal_storage_for_tests() -> None:
    """Clear the singleton pointer (used only by tests)."""
    global _journal_storage
    _journal_storage = None


@dataclass
class BarJournal:
    symbol: str
    interval: str
    open_time_ms: int
    bar_time: str
    kline: Dict[str, Any]
    phase_status: Dict[str, Any]
    decision: Optional[Dict[str, Any]]
    reports: Dict[str, Dict[str, str]]
    logs: list[Dict[str, Any]]
    executions: list[Dict[str, Any]]
    updated_at: str


class DecisionJournalStorage:
    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()
        self.database_url = database_url or settings.database_url
        self.db_path = self._resolve_db_path(self.database_url)

    @staticmethod
    def _resolve_db_path(database_url: str) -> str:
        if database_url.startswith("sqlite+aiosqlite:///"):
            raw_path = database_url.replace("sqlite+aiosqlite:///", "", 1)
        elif database_url.startswith("sqlite:///"):
            raw_path = database_url.replace("sqlite:///", "", 1)
        else:
            # fallback to local db for unsupported urls
            raw_path = "vibe_trading.db"

        return str(Path(raw_path).expanduser())

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bar_decision_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    bar_time TEXT NOT NULL,
                    kline_json TEXT NOT NULL,
                    phase_status_json TEXT NOT NULL,
                    decision_json TEXT,
                    reports_json TEXT NOT NULL,
                    logs_json TEXT NOT NULL,
                    executions_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL,
                    UNIQUE(symbol, interval, open_time_ms)
                )
                """
            )
            columns = await conn.execute("PRAGMA table_info(bar_decision_journal)")
            column_names = {row[1] for row in await columns.fetchall()}
            if "executions_json" not in column_names:
                await conn.execute(
                    "ALTER TABLE bar_decision_journal ADD COLUMN executions_json TEXT NOT NULL DEFAULT '[]'"
                )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_decision_journal_symbol_interval_time
                ON bar_decision_journal(symbol, interval, open_time_ms)
                """
            )
            await conn.commit()

    async def upsert_bar(
        self,
        *,
        symbol: str,
        interval: str,
        open_time_ms: int,
        bar_time: str,
        update: Dict[str, Any],
    ) -> None:
        existing = await self.get_bar(symbol=symbol, interval=interval, open_time_ms=open_time_ms)

        if existing is None:
            payload = {
                "kline": {},
                "phase_status": {},
                "decision": None,
                "reports": {},
                "logs": [],
                "executions": [],
            }
        else:
            payload = {
                "kline": existing.kline,
                "phase_status": existing.phase_status,
                "decision": existing.decision,
                "reports": existing.reports,
                "logs": existing.logs,
                "executions": existing.executions,
            }

        if "kline" in update and update["kline"] is not None:
            payload["kline"] = update["kline"]

        if "phase_status" in update and update["phase_status"] is not None:
            payload["phase_status"] = update["phase_status"]

        if "decision" in update:
            payload["decision"] = update["decision"]

        if "report" in update and update["report"] is not None:
            report = update["report"]
            phase = report.get("phase", "") or "unknown"
            agent = report.get("agent", "") or "unknown"
            content = report.get("content", "")
            phase_bucket = payload["reports"].setdefault(phase, {})
            phase_bucket[agent] = content

        if "log" in update and update["log"] is not None:
            payload["logs"].append(update["log"])
            # bound log size per bar to keep record compact
            payload["logs"] = payload["logs"][-120:]

        if "execution" in update and update["execution"] is not None:
            payload["executions"].append(update["execution"])
            payload["executions"] = payload["executions"][-40:]

        updated_at = datetime.now().isoformat()

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO bar_decision_journal (
                    symbol, interval, open_time_ms, bar_time,
                    kline_json, phase_status_json, decision_json,
                    reports_json, logs_json, executions_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time_ms)
                DO UPDATE SET
                    bar_time = excluded.bar_time,
                    kline_json = excluded.kline_json,
                    phase_status_json = excluded.phase_status_json,
                    decision_json = excluded.decision_json,
                    reports_json = excluded.reports_json,
                    logs_json = excluded.logs_json,
                    executions_json = excluded.executions_json,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    interval,
                    open_time_ms,
                    bar_time,
                    json.dumps(payload["kline"], ensure_ascii=False),
                    json.dumps(payload["phase_status"], ensure_ascii=False),
                    json.dumps(payload["decision"], ensure_ascii=False) if payload["decision"] is not None else None,
                    json.dumps(payload["reports"], ensure_ascii=False),
                    json.dumps(payload["logs"], ensure_ascii=False),
                    json.dumps(payload["executions"], ensure_ascii=False),
                    updated_at,
                ),
            )
            await conn.commit()

    async def get_bar(self, *, symbol: str, interval: str, open_time_ms: int) -> Optional[BarJournal]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT symbol, interval, open_time_ms, bar_time,
                       kline_json, phase_status_json, decision_json,
                       reports_json, logs_json, executions_json, updated_at
                FROM bar_decision_journal
                WHERE symbol = ? AND interval = ? AND open_time_ms = ?
                LIMIT 1
                """,
                (symbol, interval, open_time_ms),
            )
            row = await cursor.fetchone()

        if row is None:
            return None

        return BarJournal(
            symbol=row["symbol"],
            interval=row["interval"],
            open_time_ms=row["open_time_ms"],
            bar_time=row["bar_time"],
            kline=json.loads(row["kline_json"] or "{}"),
            phase_status=json.loads(row["phase_status_json"] or "{}"),
            decision=json.loads(row["decision_json"]) if row["decision_json"] else None,
            reports=json.loads(row["reports_json"] or "{}"),
            logs=json.loads(row["logs_json"] or "[]"),
            executions=json.loads(row["executions_json"] or "[]"),
            updated_at=row["updated_at"],
        )

    async def list_bars(
        self,
        *,
        symbol: Optional[str] = None,
        interval: Optional[str] = None,
        limit: int = 100,
        descending: bool = True,
    ) -> List[BarJournal]:
        """List recent bars, newest first by default.

        Filters by symbol/interval if provided. Use this to populate /api/decisions
        from the DB rather than relying on in-memory state.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if interval is not None:
            clauses.append("interval = ?")
            params.append(interval)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if descending else "ASC"
        sql = f"""
            SELECT symbol, interval, open_time_ms, bar_time,
                   kline_json, phase_status_json, decision_json,
                   reports_json, logs_json, executions_json, updated_at
            FROM bar_decision_journal
            {where}
            ORDER BY open_time_ms {order}
            LIMIT ?
        """
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()

        return [
            BarJournal(
                symbol=row["symbol"],
                interval=row["interval"],
                open_time_ms=row["open_time_ms"],
                bar_time=row["bar_time"],
                kline=json.loads(row["kline_json"] or "{}"),
                phase_status=json.loads(row["phase_status_json"] or "{}"),
                decision=json.loads(row["decision_json"]) if row["decision_json"] else None,
                reports=json.loads(row["reports_json"] or "{}"),
                logs=json.loads(row["logs_json"] or "[]"),
                executions=json.loads(row["executions_json"] or "[]"),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def count_bars(
        self,
        *,
        symbol: Optional[str] = None,
        interval: Optional[str] = None,
        with_decision_only: bool = True,
    ) -> int:
        """Count bars in the journal, optionally filtered by symbol/interval.

        Defaults to counting only rows whose `decision_json` was populated so the
        number matches what /api/decisions surfaces (one per real decision). Pass
        ``with_decision_only=False`` to count every upserted bar including
        pre-decision or partial-cycle entries.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if interval is not None:
            clauses.append("interval = ?")
            params.append(interval)
        if with_decision_only:
            clauses.append("decision_json IS NOT NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        sql = f"SELECT COUNT(*) FROM bar_decision_journal {where}"

        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
