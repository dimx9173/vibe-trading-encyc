"""Agent replay LLM response cache.

Persists agent LLM responses keyed by (model, role, prompt_hash) so re-running
a replay with unchanged prompts costs nearly nothing. Mirrors the
UsageLedger SQLite pattern (aiosqlite, explicit db_path, lazy init).

Design (grill Q8/Q9): key includes prompt_hash — prompt content changes
auto-invalidate, model swap auto-invalidates. `--no-cache` disables via
config.use_cache at the replay driver layer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import aiosqlite

logger = logging.getLogger(__name__)


def prompt_hash(prompt: str) -> str:
    """SHA-256 of the exact prompt text."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class LLMCache:
    """SQLite cache of LLM responses for agent replay."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure the cache table exists."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    model TEXT NOT NULL,
                    role TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (model, role, prompt_hash)
                )
            """)
            await db.commit()

        self._initialized = True

    async def get(self, model: str, role: str, prompt_hash_value: str) -> Optional[str]:
        """Return cached response, or None on miss."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT response FROM llm_cache WHERE model=? AND role=? AND prompt_hash=?",
                (model, role, prompt_hash_value),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return row[0]

    async def put(self, model: str, role: str, prompt_hash_value: str, response: str) -> None:
        """Store a response (upsert)."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO llm_cache (model, role, prompt_hash, response, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (model, role, prompt_hash_value, response, time.time()),
            )
            await db.commit()

    async def get_stats(self) -> Dict[str, Any]:
        """Cache size + oldest/newest timestamps (for diagnostics)."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM llm_cache"
            )
            row = await cur.fetchone()
        return {
            "entries": row[0] if row else 0,
            "oldest_ts": row[1] if row else None,
            "newest_ts": row[2] if row else None,
        }

    async def close(self) -> None:
        """No persistent connection held (aiosqlite connects per-op); no-op."""
        return None


def serialize_response(text: str) -> str:
    """Wrap raw response text for cache storage (JSON-safe)."""
    return json.dumps({"text": text}, ensure_ascii=False)


def deserialize_response(payload: str) -> str:
    """Unwrap cached payload back to raw text."""
    try:
        return json.loads(payload)["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return payload
