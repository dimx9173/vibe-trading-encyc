"""LLM 內容提取共用 helper（SWDD P0/P1 修復 2026-08-06）。

背景 bug：
1. 舊提取 ``"".join(getattr(c, "text", str(c)) for c in content)`` 對
   ``ThinkingContent``（無 text 屬性）fallback 到 ``str(c)`` → 把
   ``type='thinking' thinking='...'`` repr 垃圾塞進 response。
2. 錯誤檢查讀 ``state.error``，但 AgentState 只有 ``error_message`` →
   真實錯誤（context 過長等）永遠被吞，全顯示 "empty response"。

2026-08-09 新增 prompt_with_timeout：
   DeepSeek V4 Flash 在複雜 prompt 下會陷入 thinking loop（無限輸出
   thinking tokens 永不結束）。所有 agent 的 prompt 呼叫必須包 timeout，
   否則 process 會被外部 timeout 殺掉、決策永遠寫不進 JSONL。
"""
from __future__ import annotations

import asyncio
from typing import Any

from pi_ai import TextContent


async def prompt_with_timeout(agent: Any, prompt: str, timeout: float = 45.0) -> bool:
    """呼叫 agent.prompt() 並加上 timeout，防止 LLM thinking loop 卡死。

    Args:
        agent: pi-py Agent 實例
        prompt: 要送的 prompt
        timeout: 秒數（預設 45s）

    Returns:
        True if prompt completed (含 API error，由 caller 檢查 state.error_message)；
        False if timed out（thinking loop 被中斷）。
    """
    try:
        await asyncio.wait_for(agent.prompt(prompt), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


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
