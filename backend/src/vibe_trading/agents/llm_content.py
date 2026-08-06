"""LLM 內容提取共用 helper（SWDD P0/P1 修復 2026-08-06）。

背景 bug：
1. 舊提取 ``"".join(getattr(c, "text", str(c)) for c in content)`` 對
   ``ThinkingContent``（無 text 屬性）fallback 到 ``str(c)`` → 把
   ``type='thinking' thinking='...'`` repr 垃圾塞進 response。
2. 錯誤檢查讀 ``state.error``，但 AgentState 只有 ``error_message`` →
   真實錯誤（context 過長等）永遠被吞，全顯示 "empty response"。
"""
from __future__ import annotations

from typing import Any

from pi_ai import TextContent


def extract_text(content: Any) -> str:
    """從 assistant message 的 content 提取正式文本。

    只取 ``TextContent.text``；忽略 ``ThinkingContent``（思考過程）與
    ``ToolCall``（工具呼叫）。非 list 輸入直接 str()（相容舊行為）。
    """
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent) and block.text:
            parts.append(block.text)
    return "".join(parts)


def get_agent_error(agent: Any) -> str:
    """讀取 agent state 的錯誤訊息（正確欄位：``error_message``）。

    舊程式讀 ``state.error``（不存在）→ 永遠 None → 錯誤被吞。
    """
    state = getattr(agent, "state", None)
    if state is None:
        return ""
    return getattr(state, "error_message", None) or ""


# P1: 重試時的補償 prompt 後綴 — 引導 reasoning model 直接輸出正式內容。
RETRY_COMPENSATORY_PROMPT = (
    "\n\n[重要] 上一次回應為空。請直接輸出你的正式回答，"
    "不要只輸出思考過程。回答必須包含具體內容與結論。"
)
