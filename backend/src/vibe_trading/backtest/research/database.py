"""SQLite persistence layer for research data"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import GoalChecklistItem, GoalStatus, Hypothesis, HypothesisStatus, ResearchGoal


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _row_to_hypothesis(row: sqlite3.Row) -> Hypothesis:
    return Hypothesis(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=HypothesisStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        invalidated_at=_dt(row["invalidated_at"]),
        invalidation_reason=row["invalidation_reason"],
        evidence=json.loads(row["evidence"]),
        backtest_ids=json.loads(row["backtest_ids"]),
        alpha_factors=json.loads(row["alpha_factors"]),
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_goal(row: sqlite3.Row) -> ResearchGoal:
    return ResearchGoal(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=GoalStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=_dt(row["completed_at"]),
        checklist=[
            GoalChecklistItem(
                id=item["id"],
                description=item["description"],
                completed=item["completed"],
                completed_at=_dt(item.get("completed_at")),
                evidence=item.get("evidence"),
            )
            for item in json.loads(row["checklist"])
        ],
        budget_backtests=row["budget_backtests"],
        budget_used=row["budget_used"],
        hypothesis_ids=json.loads(row["hypothesis_ids"]),
        evidence_log=json.loads(row["evidence_log"]),
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata"]),
    )


class ResearchDatabase:
    """SQLite database for hypotheses and research goals"""

    db_path: Path

    def __init__(self, db_path: str | Path = "research.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    invalidated_at TEXT,
                    invalidation_reason TEXT,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    backtest_ids TEXT NOT NULL DEFAULT '[]',
                    alpha_factors TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    checklist TEXT NOT NULL DEFAULT '[]',
                    budget_backtests INTEGER NOT NULL DEFAULT 10,
                    budget_used INTEGER NOT NULL DEFAULT 0,
                    hypothesis_ids TEXT NOT NULL DEFAULT '[]',
                    evidence_log TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.commit()

    # === Hypothesis CRUD ===

    def save_hypothesis(self, hypothesis: Hypothesis) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hypotheses
                (id, title, description, status, created_at, updated_at,
                 invalidated_at, invalidation_reason, evidence, backtest_ids,
                 alpha_factors, tags, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hypothesis.id,
                hypothesis.title,
                hypothesis.description,
                hypothesis.status.value,
                hypothesis.created_at.isoformat(),
                hypothesis.updated_at.isoformat(),
                hypothesis.invalidated_at.isoformat() if hypothesis.invalidated_at else None,
                hypothesis.invalidation_reason,
                json.dumps(hypothesis.evidence),
                json.dumps(hypothesis.backtest_ids),
                json.dumps(hypothesis.alpha_factors),
                json.dumps(hypothesis.tags),
                json.dumps(hypothesis.metadata),
            ))
            conn.commit()

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,))
            row = cursor.fetchone()
            return _row_to_hypothesis(row) if row else None

    def list_hypotheses(
        self,
        status: Optional[HypothesisStatus] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Hypothesis]:
        query = "SELECT * FROM hypotheses WHERE 1=1"
        params: list[str] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)

        if tags:
            for tag in tags:
                escaped_tag = tag.replace("%", "\\%").replace("_", "\\_")
                query += " AND tags LIKE ? ESCAPE '\\'"
                params.append(f'%"{escaped_tag}"%')

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [_row_to_hypothesis(row) for row in cursor.fetchall()]

    def delete_hypothesis(self, hypothesis_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM hypotheses WHERE id = ?", (hypothesis_id,))
            conn.commit()
            return cursor.rowcount > 0

    # === Goal CRUD ===

    def save_goal(self, goal: ResearchGoal) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO goals
                (id, title, description, status, created_at, updated_at,
                 completed_at, checklist, budget_backtests, budget_used,
                 hypothesis_ids, evidence_log, tags, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal.id,
                goal.title,
                goal.description,
                goal.status.value,
                goal.created_at.isoformat(),
                goal.updated_at.isoformat(),
                goal.completed_at.isoformat() if goal.completed_at else None,
                json.dumps([
                    {
                        "id": item.id,
                        "description": item.description,
                        "completed": item.completed,
                        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                        "evidence": item.evidence,
                    }
                    for item in goal.checklist
                ]),
                goal.budget_backtests,
                goal.budget_used,
                json.dumps(goal.hypothesis_ids),
                json.dumps(goal.evidence_log),
                json.dumps(goal.tags),
                json.dumps(goal.metadata),
            ))
            conn.commit()

    def get_goal(self, goal_id: str) -> Optional[ResearchGoal]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
            row = cursor.fetchone()
            return _row_to_goal(row) if row else None

    def list_goals(
        self,
        status: Optional[GoalStatus] = None,
        limit: int = 100,
    ) -> List[ResearchGoal]:
        query = "SELECT * FROM goals WHERE 1=1"
        params: list[str] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [_row_to_goal(row) for row in cursor.fetchall()]

    def delete_goal(self, goal_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
            conn.commit()
            return cursor.rowcount > 0
