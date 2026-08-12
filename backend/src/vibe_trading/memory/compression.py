"""上下文壓縮層 - 5 級壓縮策略"""
from __future__ import annotations

import logging
from typing import List, Optional
from dataclasses import dataclass

from .fts5_memory import FTS5Entry

logger = logging.getLogger(__name__)


@dataclass
class CompressionConfig:
    """壓縮配置"""
    max_tokens: int = 4000
    compression_levels: Optional[List[int]] = None

    def __post_init__(self):
        if self.compression_levels is None:
            self.compression_levels = [
                self.max_tokens,
                int(self.max_tokens * 0.75),
                int(self.max_tokens * 0.50),
                int(self.max_tokens * 0.25),
                int(self.max_tokens * 0.10),
            ]


class ContextCompressor:
    """
    上下文壓縮器

    實現 5 級壓縮策略：
    Level 0: 完整內容（無壓縮）
    Level 1: 輕度壓縮（保留關鍵信息）
    Level 2: 中度壓縮（摘要 + 關鍵數據）
    Level 3: 重度壓縮（僅核心結論）
    Level 4: 極度壓縮（單行摘要）
    """

    def __init__(self, config: Optional[CompressionConfig] = None):
        self.config = config or CompressionConfig()

    def compress_memories(
        self,
        memories: List[FTS5Entry],
        target_tokens: Optional[int] = None,
    ) -> str:
        if not memories:
            return ""

        full_text = self._format_memories_full(memories)
        estimated_tokens = len(full_text.split()) * 1.3

        if target_tokens is None:
            target_tokens = self.config.max_tokens

        if estimated_tokens <= target_tokens:
            self._record_compression(int(estimated_tokens), int(estimated_tokens), 0)
            return full_text

        for level in range(1, 5):
            compressed = self._compress_at_level(memories, level)
            compressed_tokens = len(compressed.split()) * 1.3

            if compressed_tokens <= target_tokens:
                self._record_compression(int(estimated_tokens), int(compressed_tokens), level)
                logger.info(f"Compression level {level} selected ({compressed_tokens:.0f} tokens)")
                return compressed

        result = self._compress_at_level(memories, 4)
        self._record_compression(int(estimated_tokens), int(len(result.split()) * 1.3), 4)
        return result

    def _record_compression(self, original_tokens: int, compressed_tokens: int, level: int):
        try:
            from .monitor import get_memory_monitor
            get_memory_monitor().record_compression(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                compression_level=level,
            )
        except Exception:
            pass

    def _format_memories_full(self, memories: List[FTS5Entry]) -> str:
        lines = []
        for mem in memories:
            lines.append(f"### Memory #{mem.id}")
            lines.append(f"**Situation**: {mem.situation}")
            lines.append(f"**Advice**: {mem.advice}")
            if mem.outcome:
                lines.append(f"**Outcome**: {mem.outcome}")
            if mem.pnl is not None:
                lines.append(f"**PnL**: {mem.pnl:.2f}%")
            if mem.alpha is not None:
                lines.append(f"**Alpha**: {mem.alpha:+.2f}%")
            if mem.symbol:
                lines.append(f"**Symbol**: {mem.symbol}")
            if mem.tags:
                lines.append(f"**Tags**: {mem.tags}")
            lines.append("")
        return "\n".join(lines)

    def _compress_at_level(self, memories: List[FTS5Entry], level: int) -> str:
        if level == 1:
            return self._level1_light_compression(memories)
        elif level == 2:
            return self._level2_medium_compression(memories)
        elif level == 3:
            return self._level3_heavy_compression(memories)
        elif level == 4:
            return self._level4_extreme_compression(memories)
        else:
            return self._format_memories_full(memories)

    def _level1_light_compression(self, memories: List[FTS5Entry]) -> str:
        lines = []
        for mem in memories:
            lines.append(f"#{mem.id}: {mem.situation}")
            lines.append(f"  -> {mem.advice}")
            if mem.outcome:
                lines.append(f"  Outcome: {mem.outcome}")
            if mem.pnl is not None:
                lines.append(f"  PnL: {mem.pnl:.2f}%")
        return "\n".join(lines)

    def _level2_medium_compression(self, memories: List[FTS5Entry]) -> str:
        lines = []
        for mem in memories:
            pnl_str = f" (PnL: {mem.pnl:.2f}%)" if mem.pnl is not None else ""
            lines.append(f"#{mem.id}: {mem.situation} -> {mem.advice}{pnl_str}")
        return "\n".join(lines)

    def _level3_heavy_compression(self, memories: List[FTS5Entry]) -> str:
        sorted_memories = sorted(
            memories,
            key=lambda m: abs(m.pnl) if m.pnl is not None else 0,
            reverse=True,
        )

        lines = []
        for mem in sorted_memories[:5]:
            pnl_str = f" [{mem.pnl:+.2f}%]" if mem.pnl is not None else ""
            lines.append(f"- {mem.advice[:80]}{pnl_str}")
        return "\n".join(lines)

    def _level4_extreme_compression(self, memories: List[FTS5Entry]) -> str:
        if not memories:
            return ""

        total = len(memories)
        with_pnl = [m for m in memories if m.pnl is not None]
        avg_pnl = sum(m.pnl for m in with_pnl) / len(with_pnl) if with_pnl else 0

        all_text = " ".join([m.situation + " " + m.advice for m in memories])
        words = all_text.lower().split()
        from collections import Counter
        word_freq = Counter(words)
        top_keywords = [w for w, _ in word_freq.most_common(5)]

        summary = f"{total} memories"
        if with_pnl:
            summary += f", avg PnL: {avg_pnl:+.2f}%"
        if top_keywords:
            summary += f", keywords: {', '.join(top_keywords)}"

        return summary

    def compress_for_prompt(
        self,
        memories: List[FTS5Entry],
        available_tokens: int,
    ) -> str:
        return self.compress_memories(memories, target_tokens=available_tokens)
