"""
Research Database

SQLite database for storing hypotheses and research goals.
Provides persistent storage with efficient querying.
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from .models import Hypothesis, HypothesisStatus, ResearchGoal, GoalStatus


class ResearchDatabase:
    """Research database manager"""
    
    def __init__(self, db_path: str = "research.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            # Hypotheses table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    backtest_results TEXT NOT NULL DEFAULT '[]',
                    live_results TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    author TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    validated_at TEXT,
                    invalidated_at TEXT,
                    invalidation_reason TEXT NOT NULL DEFAULT ''
                )
            """)
            
            # Research goals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    checklist TEXT NOT NULL DEFAULT '[]',
                    budget_backtests INTEGER NOT NULL DEFAULT 10,
                    budget_used INTEGER NOT NULL DEFAULT 0,
                    budget_capital REAL NOT NULL DEFAULT 0.0,
                    budget_capital_used REAL NOT NULL DEFAULT 0.0,
                    evidence_log TEXT NOT NULL DEFAULT '[]',
                    hypothesis_ids TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    author TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    completed_at TEXT,
                    completion_notes TEXT NOT NULL DEFAULT ''
                )
            """)
            
            # Indexes for efficient querying
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hypotheses_tags ON hypotheses(tags)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON research_goals(status)")
            
            conn.commit()
    
    # ========================================================================
    # Hypothesis Operations
    # ========================================================================
    
    async def save_hypothesis(self, hypothesis: Hypothesis) -> bool:
        """Save or update a hypothesis"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hypotheses 
                (id, title, description, status, created_at, updated_at,
                 evidence, backtest_results, live_results, tags, author, notes,
                 validated_at, invalidated_at, invalidation_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hypothesis.id,
                hypothesis.title,
                hypothesis.description,
                hypothesis.status.value,
                hypothesis.created_at.isoformat(),
                hypothesis.updated_at.isoformat(),
                json.dumps(hypothesis.evidence),
                json.dumps(hypothesis.backtest_results),
                json.dumps(hypothesis.live_results),
                json.dumps(hypothesis.tags),
                hypothesis.author,
                hypothesis.notes,
                hypothesis.validated_at.isoformat() if hypothesis.validated_at else None,
                hypothesis.invalidated_at.isoformat() if hypothesis.invalidated_at else None,
                hypothesis.invalidation_reason,
            ))
            conn.commit()
        return True
    
    async def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a hypothesis by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM hypotheses WHERE id = ?",
                (hypothesis_id,)
            )
            row = cursor.fetchone()
        
        if not row:
            return None
        
        return self._row_to_hypothesis(row)
    
    async def get_all_hypotheses(self, status: Optional[HypothesisStatus] = None) -> List[Hypothesis]:
        """Get all hypotheses, optionally filtered by status"""
        query = "SELECT * FROM hypotheses"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY updated_at DESC"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        
        return [self._row_to_hypothesis(row) for row in rows]
    
    async def search_hypotheses(self, query: str) -> List[Hypothesis]:
        """Search hypotheses by title, description, or tags"""
        search_term = f"%{query}%"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM hypotheses 
                WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?
                ORDER BY updated_at DESC
            """, (search_term, search_term, search_term))
            rows = cursor.fetchall()
        
        return [self._row_to_hypothesis(row) for row in rows]
    
    async def delete_hypothesis(self, hypothesis_id: str) -> bool:
        """Delete a hypothesis"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM hypotheses WHERE id = ?", (hypothesis_id,))
            conn.commit()
        return True
    
    def _row_to_hypothesis(self, row) -> Hypothesis:
        """Convert database row to Hypothesis object"""
        return Hypothesis(
            id=row[0],
            title=row[1],
            description=row[2],
            status=HypothesisStatus(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
            evidence=json.loads(row[6]),
            backtest_results=json.loads(row[7]),
            live_results=json.loads(row[8]),
            tags=json.loads(row[9]),
            author=row[10],
            notes=row[11],
            validated_at=datetime.fromisoformat(row[12]) if row[12] else None,
            invalidated_at=datetime.fromisoformat(row[13]) if row[13] else None,
            invalidation_reason=row[14],
        )
    
    # ========================================================================
    # Research Goal Operations
    # ========================================================================
    
    async def save_goal(self, goal: ResearchGoal) -> bool:
        """Save or update a research goal"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO research_goals 
                (id, title, description, status, created_at, updated_at,
                 checklist, budget_backtests, budget_used, budget_capital, budget_capital_used,
                 evidence_log, hypothesis_ids, tags, author, notes,
                 completed_at, completion_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal.id,
                goal.title,
                goal.description,
                goal.status.value,
                goal.created_at.isoformat(),
                goal.updated_at.isoformat(),
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
                goal.budget_capital,
                goal.budget_capital_used,
                json.dumps(goal.evidence_log),
                json.dumps(goal.hypothesis_ids),
                json.dumps(goal.tags),
                goal.author,
                goal.notes,
                goal.completed_at.isoformat() if goal.completed_at else None,
                goal.completion_notes,
            ))
            conn.commit()
        return True
    
    async def get_goal(self, goal_id: str) -> Optional[ResearchGoal]:
        """Get a research goal by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM research_goals WHERE id = ?",
                (goal_id,)
            )
            row = cursor.fetchone()
        
        if not row:
            return None
        
        return self._row_to_goal(row)
    
    async def get_all_goals(self, status: Optional[GoalStatus] = None) -> List[ResearchGoal]:
        """Get all research goals, optionally filtered by status"""
        query = "SELECT * FROM research_goals"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY updated_at DESC"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        
        return [self._row_to_goal(row) for row in rows]
    
    async def delete_goal(self, goal_id: str) -> bool:
        """Delete a research goal"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM research_goals WHERE id = ?", (goal_id,))
            conn.commit()
        return True
    
    def _row_to_goal(self, row) -> ResearchGoal:
        """Convert database row to ResearchGoal object"""
        from .models import GoalChecklistItem
        
        checklist_data = json.loads(row[6])
        checklist = [
            GoalChecklistItem(
                id=item["id"],
                description=item["description"],
                completed=item["completed"],
                completed_at=datetime.fromisoformat(item["completed_at"]) if item.get("completed_at") else None,
                evidence=item.get("evidence", ""),
            )
            for item in checklist_data
        ]
        
        return ResearchGoal(
            id=row[0],
            title=row[1],
            description=row[2],
            status=GoalStatus(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
            checklist=checklist,
            budget_backtests=row[7],
            budget_used=row[8],
            budget_capital=row[9],
            budget_capital_used=row[10],
            evidence_log=json.loads(row[11]),
            hypothesis_ids=json.loads(row[12]),
            tags=json.loads(row[13]),
            author=row[14],
            notes=row[15],
            completed_at=datetime.fromisoformat(row[16]) if row[16] else None,
            completion_notes=row[17],
        )
