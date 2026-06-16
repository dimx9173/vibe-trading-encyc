"""
BM25 记忆系统

基于 BM25 算法的离线记忆系统，用于存储和检索历史交易经验。
借鉴 TradingAgents 项目的实现。
"""
import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """记忆条目"""
    situation: str
    advice: str
    outcome: Optional[str] = None
    pnl: Optional[float] = None
    timestamp: float = 0
    symbol: Optional[str] = None
    benchmark_return: Optional[float] = None  # 基准同期回报%
    alpha: Optional[float] = None  # 市场调整后超额回报%

    def to_dict(self) -> dict:
        return {
            "situation": self.situation,
            "advice": self.advice,
            "outcome": self.outcome,
            "pnl": self.pnl,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "benchmark_return": self.benchmark_return,
            "alpha": self.alpha,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(
            situation=data["situation"],
            advice=data["advice"],
            outcome=data.get("outcome"),
            pnl=data.get("pnl"),
            timestamp=data.get("timestamp", 0),
            symbol=data.get("symbol"),
            benchmark_return=data.get("benchmark_return"),
            alpha=data.get("alpha"),
        )


class BM25Memory:
    """
    BM25 记忆系统

    使用 BM25 算法进行相关性检索的离线记忆系统。
    无需 API 调用，基于词汇相似性进行检索。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        初始化 BM25 记忆系统

        Args:
            k1: 词频饱和参数（默认 1.5）
            b: 长度归一化参数（默认 0.75）
        """
        self.k1 = k1
        self.b = b
        self.documents: List[MemoryEntry] = []
        self.doc_freqs: List[Dict] = []
        self.idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0

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
        """
        添加记忆条目

        Args:
            situation: 市场情况描述
            advice: 当时给出的建议/决策
            outcome: 结果描述（可选）
            pnl: 盈亏（可选）
            symbol: 交易对（可选）
            benchmark_return: 基准同期回报%（可选）
            alpha: 市场调整后超额回报%（可选）
        """
        import time

        entry = MemoryEntry(
            situation=situation,
            advice=advice,
            outcome=outcome,
            pnl=pnl,
            timestamp=time.time(),
            symbol=symbol,
            benchmark_return=benchmark_return,
            alpha=alpha,
        )

        self.documents.append(entry)
        self._update_index()

        logger.info(f"Added memory entry: {situation[:50]}...")

    def _update_index(self) -> None:
        """更新 BM25 索引"""
        if not self.documents:
            return

        # 计算文档频率
        self.doc_freqs = []
        for doc in self.documents:
            tokens = self._tokenize(doc.situation + " " + doc.advice)
            freq = Counter(tokens)
            self.doc_freqs.append(freq)

        # 计算逆文档频率
        n_docs = len(self.documents)
        all_tokens = set()
        for freq in self.doc_freqs:
            all_tokens.update(freq.keys())

        self.idf = {}
        for token in all_tokens:
            df = sum(1 for freq in self.doc_freqs if token in freq)
            idf = np.log((n_docs - df + 0.5) / (df + 0.5) + 1)
            self.idf[token] = idf

        # 计算平均文档长度
        doc_lengths = [sum(freq.values()) for freq in self.doc_freqs]
        self.avg_doc_len = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0

    def _tokenize(self, text: str) -> List[str]:
        """简单的分词函数"""
        # 转小写，按空格分词，去标点
        text = text.lower()
        for char in ",.!?;:'\"()[]{}":
            text = text.replace(char, " ")
        tokens = [t for t in text.split() if len(t) > 1]
        return tokens

    def _calculate_scores(self, query: str) -> np.ndarray:
        """计算 BM25 分数"""
        if not self.documents:
            return np.array([])

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return np.zeros(len(self.documents))

        scores = np.zeros(len(self.documents))

        for i, doc_freq in enumerate(self.doc_freqs):
            doc_len = sum(doc_freq.values())

            for token in query_tokens:
                if token in doc_freq:
                    tf = doc_freq[token]
                    idf = self.idf.get(token, 0)

                    # BM25 公式
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / (self.avg_doc_len + 1e-8)))
                    scores[i] += idf * (numerator / (denominator + 1e-8))

        return scores

    def retrieve_relevant(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1,
    ) -> List[str]:
        """
        检索相关的历史记忆

        Args:
            query: 查询文本
            top_k: 返回的最相关文档数量
            min_score: 最小相关性分数阈值

        Returns:
            相关的历史建议列表
        """
        if not self.documents:
            return []

        scores = self._calculate_scores(query)

        # 获取最高分的文档
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] >= min_score:
                doc = self.documents[idx]
                advice = f"Situation: {doc.situation}\nAdvice: {doc.advice}"
                if doc.outcome:
                    advice += f"\nOutcome: {doc.outcome}"
                if doc.pnl is not None:
                    advice += f"\nPnL: {doc.pnl:.2f}%"
                if doc.alpha is not None:
                    advice += f"\nAlpha (mkt-adj): {doc.alpha:+.2f}%"
                results.append(advice)

        return results

    def get_all_memories(self) -> List[MemoryEntry]:
        """获取所有记忆"""
        return self.documents.copy()

    def get_cross_ticker_lessons(self, top_k: int = 3) -> str:
        """
        聚合跨币种的胜负经验，返回精简摘要供 PM 参考（纯聚合，无 LLM）。

        借鉴 TradingAgents 的"跨 ticker 教训"思路：把高 alpha 的赢家模式与
        负 alpha 的输家模式提炼出来，让单一币种决策也能看到全局规律。
        无 alpha 的条目不参与（无法判断决策质量）。
        """
        with_alpha = [d for d in self.documents if d.alpha is not None]
        if not with_alpha:
            return ""

        winners = sorted(
            [d for d in with_alpha if d.alpha > 0],
            key=lambda d: d.alpha,
            reverse=True,
        )[:top_k]
        losers = sorted(
            [d for d in with_alpha if d.alpha < 0], key=lambda d: d.alpha
        )[:top_k]

        lines: List[str] = []
        if winners:
            lines.append("Winning patterns (positive alpha):")
            for d in winners:
                lines.append(
                    f"  + [{d.symbol or '?'} a{d.alpha:+.1f}%] {d.advice[:80]}"
                )
        if losers:
            lines.append("Losing patterns (negative alpha):")
            for d in losers:
                lines.append(
                    f"  - [{d.symbol or '?'} a{d.alpha:+.1f}%] {d.advice[:80]}"
                )
        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有记忆"""
        self.documents = []
        self.doc_freqs = []
        self.idf = {}
        self.avg_doc_len = 0

    def size(self) -> int:
        """获取记忆数量"""
        return len(self.documents)


class PersistentMemory(BM25Memory):
    """
    持久化记忆系统

    支持将记忆保存到文件和从文件加载。
    """

    def __init__(
        self,
        storage_path: str = "./memory_storage.pkl",
        k1: float = 1.5,
        b: float = 0.75,
    ):
        super().__init__(k1, b)
        self.storage_path = Path(storage_path)

    def save(self) -> None:
        """保存记忆到文件"""
        try:
            data = {
                "documents": [doc.to_dict() for doc in self.documents],
                "k1": self.k1,
                "b": self.b,
            }

            with open(self.storage_path, "wb") as f:
                pickle.dump(data, f)

            logger.info(f"Saved {len(self.documents)} memories to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save memories: {e}")

    def load(self) -> bool:
        """从文件加载记忆"""
        if not self.storage_path.exists():
            logger.info(f"No existing memory file at {self.storage_path}")
            return False

        try:
            with open(self.storage_path, "rb") as f:
                data = pickle.load(f)

            self.documents = [MemoryEntry.from_dict(doc) for doc in data["documents"]]
            self.k1 = data.get("k1", 1.5)
            self.b = data.get("b", 0.75)

            # 重建索引
            self._update_index()

            logger.info(f"Loaded {len(self.documents)} memories from {self.storage_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load memories: {e}")
            return False

    def export_to_json(self, json_path: str) -> None:
        """导出记忆到 JSON 文件"""
        try:
            data = [doc.to_dict() for doc in self.documents]

            with open(json_path, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Exported {len(self.documents)} memories to {json_path}")
        except Exception as e:
            logger.error(f"Failed to export memories: {e}")

    def import_from_json(self, json_path: str) -> int:
        """从 JSON 文件导入记忆"""
        try:
            with open(json_path, "r") as f:
                data = json.load(f)

            count = 0
            for doc_data in data:
                self.documents.append(MemoryEntry.from_dict(doc_data))
                count += 1

            # 重建索引
            self._update_index()

            logger.info(f"Imported {count} memories from {json_path}")
            return count
        except Exception as e:
            logger.error(f"Failed to import memories: {e}")
            return 0


def create_memory_from_settings():
    """
    根据全局 settings 构造并加载持久化记忆。

    enable_memory 关闭时返回 None。
    """
    from vibe_trading.config.settings import get_settings

    settings = get_settings()
    if not settings.enable_memory:
        return None

    memory = PersistentMemory(storage_path=settings.memory_storage_path)
    memory.load()  # 加载历史记忆（不存在时安全返回 False）
    return memory
