"""
Decision Checkpoint Storage

Persist decision phase checkpoints to SQLite for crash recovery.
Each checkpoint captures the DecisionContext at a phase boundary,
allowing resume_from() to skip already-completed phases.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

CREATE_CHECKPOINTS_TABLE = """
CREATE TABLE IF NOT EXISTS decision_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    completed_phase TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(decision_id, completed_phase)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_decision ON decision_checkpoints(decision_id);
"""


class DecisionCheckpointStore:
    """SQLite-backed checkpoint store for decision flow crash recovery."""

    def __init__(self, db_path: str = "vibe_trading.db"):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

        # For in-memory databases, keep a persistent connection
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.executescript(CREATE_CHECKPOINTS_TABLE)
            self._conn.commit()
        else:
            self._init_db()

    def _init_db(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(CREATE_CHECKPOINTS_TABLE)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to init checkpoint table: {e}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection. For in-memory, reuse; for file, create new."""
        if self._conn is not None:
            return self._conn
        return sqlite3.connect(self._db_path)

    def _close_if_file(self, conn: sqlite3.Connection) -> None:
        """Close connection only if it's a file-based one (not in-memory)."""
        if self._conn is None:
            conn.close()

    def save_checkpoint(
        self,
        decision_id: str,
        symbol: str,
        interval: str,
        completed_phase: str,
        context: dict[str, Any],
    ) -> int:
        """Save a checkpoint after a phase completes.

        Returns:
            The checkpoint row id, or -1 on failure.
        """
        try:
            conn = self._get_connection()
            context_json = json.dumps(context, ensure_ascii=False, default=str)
            cursor = conn.execute(
                """INSERT OR REPLACE INTO decision_checkpoints
                   (decision_id, symbol, interval, completed_phase, context_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    symbol,
                    interval,
                    completed_phase,
                    context_json,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid
            self._close_if_file(conn)
            logger.info(
                f"Checkpoint saved: decision={decision_id} phase={completed_phase} id={row_id}"
            )
            return row_id if row_id is not None else -1
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            return -1

    def get_latest_checkpoint(self, decision_id: str) -> dict[str, Any] | None:
        """Get the latest checkpoint for a decision.

        Returns:
            dict with keys: id, decision_id, symbol, interval, completed_phase,
            context (parsed from JSON), created_at.
            None if no checkpoint exists.
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT id, decision_id, symbol, interval, completed_phase,
                          context_json, created_at
                   FROM decision_checkpoints
                   WHERE decision_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (decision_id,),
            ).fetchone()
            self._close_if_file(conn)
            if row is None:
                return None
            return {
                "id": row["id"],
                "decision_id": row["decision_id"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "completed_phase": row["completed_phase"],
                "context": json.loads(row["context_json"]),
                "created_at": row["created_at"],
            }
        except Exception as e:
            logger.error(f"Failed to get checkpoint: {e}")
            return None

    def get_all_checkpoints(self) -> list[dict[str, Any]]:
        """Get all checkpoints (for testing)."""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, decision_id, symbol, interval, completed_phase,
                          context_json, created_at
                   FROM decision_checkpoints
                   ORDER BY id ASC"""
            ).fetchall()
            self._close_if_file(conn)
            return [
                {
                    "id": r["id"],
                    "decision_id": r["decision_id"],
                    "symbol": r["symbol"],
                    "interval": r["interval"],
                    "completed_phase": r["completed_phase"],
                    "context": json.loads(r["context_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get all checkpoints: {e}")
            return []

    def get_checkpoints(self, decision_id: str) -> list[dict[str, Any]]:
        """Get all checkpoints for a decision, ordered by id."""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, decision_id, symbol, interval, completed_phase,
                          context_json, created_at
                   FROM decision_checkpoints
                   WHERE decision_id = ?
                   ORDER BY id ASC""",
                (decision_id,),
            ).fetchall()
            self._close_if_file(conn)
            return [
                {
                    "id": r["id"],
                    "decision_id": r["decision_id"],
                    "symbol": r["symbol"],
                    "interval": r["interval"],
                    "completed_phase": r["completed_phase"],
                    "context": json.loads(r["context_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get checkpoints: {e}")
            return []

    def delete_checkpoints(self, decision_id: str) -> int:
        """Delete all checkpoints for a decision. Returns count deleted."""
        try:
            conn = self._get_connection()
            cursor = conn.execute(
                "DELETE FROM decision_checkpoints WHERE decision_id = ?",
                (decision_id,),
            )
            conn.commit()
            count = cursor.rowcount
            self._close_if_file(conn)
            return count
        except Exception as e:
            logger.error(f"Failed to delete checkpoints: {e}")
            return 0
