"""混合记忆后端 - BM25 + FTS5 双引擎

保持与现有 PersistentMemory 完全兼容的接口，
同时提供 FTS5 全文检索的性能优势。
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import List, Dict, Optional

from .memory import BM25Memory, MemoryEntry
from .fts5_memory import FTS5Memory

logger = logging.getLogger(__name__)


class HybridMemory(BM25Memory):
    """
    混合记忆系统

    结合 BM25 和 FTS5 的优势：
    - FTS5 作为主搜索引擎（快速、支持复杂查询）
    - BM25 作为后备引擎（兼容性、离线可用）
    - 自动数据同步和迁移

    完全兼容 PersistentMemory 接口，可无缝替换。
    """

    storage_path: Path
    use_fts5: bool
    fts5_memory: Optional[FTS5Memory]

    def __init__(
        self,
        storage_path: str = "./memory_storage.pkl",
        fts5_db_path: str = "./memory_fts5.db",
        k1: float = 1.5,
        b: float = 0.75,
        use_fts5: bool = True,
    ):
        super().__init__(k1, b)

        self.storage_path = Path(storage_path)
        self.use_fts5 = use_fts5
        self.fts5_memory = None

        if use_fts5:
            try:
                self.fts5_memory = FTS5Memory(fts5_db_path)
                logger.info("FTS5 backend initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize FTS5, falling back to BM25: {e}")
                self.use_fts5 = False

        self._load_existing_data()

    def _load_existing_data(self):
        """加载现有 BM25 数据并迁移到 FTS5"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "rb") as f:
                    data = pickle.load(f)

                if isinstance(data, dict) and "documents" in data:
                    for doc_data in data["documents"]:
                        entry = MemoryEntry.from_dict(doc_data)
                        self.documents.append(entry)
                        self._update_index()

                        if self.use_fts5 and self.fts5_memory:
                            self.fts5_memory.add_memory(
                                situation=entry.situation,
                                advice=entry.advice,
                                outcome=entry.outcome,
                                pnl=entry.pnl,
                                symbol=entry.symbol,
                                benchmark_return=entry.benchmark_return,
                                alpha=entry.alpha,
                                timestamp=entry.timestamp,
                            )

                    logger.info(f"Loaded {len(self.documents)} memories from BM25 storage")
            except Exception as e:
                logger.warning(f"Failed to load existing BM25 data: {e}")

    def add_memory(
        self,
        situation: str,
        advice: str,
        outcome: Optional[str] = None,
        pnl: Optional[float] = None,
        symbol: Optional[str] = None,
        benchmark_return: Optional[float] = None,
        alpha: Optional[float] = None,
    ) -> None:
        super().add_memory(
            situation=situation,
            advice=advice,
            outcome=outcome,
            pnl=pnl,
            symbol=symbol,
            benchmark_return=benchmark_return,
            alpha=alpha,
        )

        if self.use_fts5 and self.fts5_memory:
            try:
                self.fts5_memory.add_memory(
                    situation=situation,
                    advice=advice,
                    outcome=outcome,
                    pnl=pnl,
                    symbol=symbol,
                    benchmark_return=benchmark_return,
                    alpha=alpha,
                )
            except Exception as e:
                logger.warning(f"Failed to add memory to FTS5: {e}")

    def retrieve_relevant(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1,
    ) -> List[str]:
        if self.use_fts5 and self.fts5_memory:
            try:
                results = self.fts5_memory.search(query, top_k=top_k)

                formatted_results: List[str] = []
                for entry in results:
                    advice = f"Situation: {entry.situation}\nAdvice: {entry.advice}"
                    if entry.outcome:
                        advice += f"\nOutcome: {entry.outcome}"
                    if entry.pnl is not None:
                        advice += f"\nPnL: {entry.pnl:.2f}%"
                    if entry.alpha is not None:
                        advice += f"\nAlpha (mkt-adj): {entry.alpha:+.2f}%"
                    formatted_results.append(advice)

                if formatted_results:
                    return formatted_results

            except Exception as e:
                logger.warning(f"FTS5 search failed, falling back to BM25: {e}")

        return super().retrieve_relevant(query, top_k, min_score)

    def save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "documents": [doc.to_dict() for doc in self.documents],
                "k1": self.k1,
                "b": self.b,
            }

            with open(self.storage_path, "wb") as f:
                pickle.dump(data, f)

            logger.info(f"Saved {len(self.documents)} memories to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save BM25 memory: {e}")

    def load(self) -> bool:
        return self.storage_path.exists()

    def clear(self) -> None:
        super().clear()

        if self.use_fts5 and self.fts5_memory:
            try:
                self.fts5_memory.clear()
            except Exception as e:
                logger.warning(f"Failed to clear FTS5 memory: {e}")

    def size(self) -> int:
        return len(self.documents)

    def get_fts5_stats(self) -> Optional[Dict[str, int]]:
        if self.use_fts5 and self.fts5_memory:
            return self.fts5_memory.get_stats()
        return None


def create_hybrid_memory_from_settings():
    """从设置创建混合记忆系统"""
    from vibe_trading.config.settings import get_settings

    settings = get_settings()

    memory = HybridMemory(
        storage_path=settings.memory_storage_path,
        fts5_db_path=settings.memory_storage_path.replace(".pkl", "_fts5.db"),
        use_fts5=True,
    )

    return memory
