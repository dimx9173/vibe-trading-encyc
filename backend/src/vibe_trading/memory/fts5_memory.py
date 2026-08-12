"""FTS5 全文檢索後端 - SQLite FTS5 實現"""
from __future__ import annotations

import sqlite3
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FTS5Entry:
    """FTS5 記憶條目"""
    id: Optional[int] = None
    situation: str = ""
    advice: str = ""
    outcome: Optional[str] = None
    pnl: Optional[float] = None
    timestamp: float = 0.0
    symbol: Optional[str] = None
    benchmark_return: Optional[float] = None
    alpha: Optional[float] = None
    tags: str = ""


class FTS5Memory:
    """
    FTS5 全文檢索記憶系統

    使用 SQLite FTS5 實現高效的全文檢索，支持：
    - 快速全文搜索
    - 布林查詢（AND/OR/NOT）
    - 短語搜索
    - 前綴搜索
    - 排名（BM25）
    """

    def __init__(self, db_path: str = "memory_fts5.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    situation TEXT NOT NULL,
                    advice TEXT NOT NULL,
                    outcome TEXT,
                    pnl REAL,
                    timestamp REAL,
                    symbol TEXT,
                    benchmark_return REAL,
                    alpha REAL,
                    tags TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    situation, advice, outcome, tags,
                    content=memories, content_rowid=id
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, situation, advice, outcome, tags)
                    VALUES (new.id, new.situation, new.advice, new.outcome, new.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, situation, advice, outcome, tags)
                    VALUES ('delete', old.id, old.situation, old.advice, old.outcome, old.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, situation, advice, outcome, tags)
                    VALUES ('delete', old.id, old.situation, old.advice, old.outcome, old.tags);
                    INSERT INTO memories_fts(rowid, situation, advice, outcome, tags)
                    VALUES (new.id, new.situation, new.advice, new.outcome, new.tags);
                END
            """)
            conn.commit()

    def add_memory(
        self,
        situation: str,
        advice: str,
        outcome: Optional[str] = None,
        pnl: Optional[float] = None,
        symbol: Optional[str] = None,
        benchmark_return: Optional[float] = None,
        alpha: Optional[float] = None,
        tags: str = "",
        timestamp: Optional[float] = None,
    ) -> int:
        if timestamp is None:
            timestamp = time.time()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO memories (situation, advice, outcome, pnl, timestamp, symbol, benchmark_return, alpha, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (situation, advice, outcome, pnl, timestamp, symbol, benchmark_return, alpha, tags),
            )
            conn.commit()
            return cursor.lastrowid

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        symbol_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
    ) -> List[FTS5Entry]:
        start_time = time.time()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            sql = "SELECT m.*, rank FROM memories_fts fts JOIN memories m ON m.id = fts.rowid WHERE memories_fts MATCH ?"
            params: list = [query]

            if symbol_filter:
                sql += " AND m.symbol = ?"
                params.append(symbol_filter)

            if tag_filter:
                sql += " AND m.tags LIKE ?"
                params.append(f"%{tag_filter}%")

            sql += " ORDER BY rank LIMIT ?"
            params.append(top_k)

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        latency_ms = (time.time() - start_time) * 1000

        # Record search metric
        try:
            from .monitor import get_memory_monitor
            get_memory_monitor().record_search(
                query=query,
                engine="fts5",
                latency_ms=latency_ms,
                results_count=len(rows),
                top_k=top_k,
            )
        except Exception:
            pass

        results: List[FTS5Entry] = []
        for row in rows:
            score = -row["rank"] if row["rank"] < 0 else 0.0
            if score >= min_score:
                results.append(FTS5Entry(
                    id=row["id"],
                    situation=row["situation"],
                    advice=row["advice"],
                    outcome=row["outcome"],
                    pnl=row["pnl"],
                    timestamp=row["timestamp"],
                    symbol=row["symbol"],
                    benchmark_return=row["benchmark_return"],
                    alpha=row["alpha"],
                    tags=row["tags"],
                ))

        return results

    def get_memory(self, memory_id: int) -> Optional[FTS5Entry]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()
            if row:
                return FTS5Entry(
                    id=row["id"], situation=row["situation"], advice=row["advice"],
                    outcome=row["outcome"], pnl=row["pnl"], timestamp=row["timestamp"],
                    symbol=row["symbol"], benchmark_return=row["benchmark_return"],
                    alpha=row["alpha"], tags=row["tags"],
                )
            return None

    def update_memory(self, memory_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [memory_id]
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"UPDATE memories SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_memories(self, limit: int = 1000) -> List[FTS5Entry]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [
                FTS5Entry(
                    id=row["id"], situation=row["situation"], advice=row["advice"],
                    outcome=row["outcome"], pnl=row["pnl"], timestamp=row["timestamp"],
                    symbol=row["symbol"], benchmark_return=row["benchmark_return"],
                    alpha=row["alpha"], tags=row["tags"],
                )
                for row in cursor.fetchall()
            ]

    def get_stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM memories WHERE symbol IS NOT NULL").fetchone()[0]
            with_pnl = conn.execute("SELECT COUNT(*) FROM memories WHERE pnl IS NOT NULL").fetchone()[0]
            return {"total_memories": total, "unique_symbols": symbols, "memories_with_pnl": with_pnl}

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM memories")
            conn.execute("DELETE FROM memories_fts")
            conn.commit()
