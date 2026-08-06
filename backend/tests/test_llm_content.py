"""
SWDD P0/P1 修復測試（2026-08-06）— LLM 內容提取 + agent 錯誤欄位。

背景 bug（3 個疊加）：
1. `getattr(c, "text", str(c))` 對 ThinkingContent 無 text 屬性 → fallback str(c)
   輸出 repr 垃圾（type='thinking' thinking='...'）→ 污染辯論 history
2. AgentState 只有 error_message，舊程式檢查 state.error → 永遠 None → 真實錯誤被吞
3. agent 跨週期重用，state.messages 無限累積 → context 爆炸

修復：共用 extract_text() / get_agent_error() helper。
"""
import pytest
from unittest.mock import AsyncMock, patch

from pi_ai import AssistantMessage, TextContent, ThinkingContent

from vibe_trading.agents.llm_content import extract_text, get_agent_error


# ---------------------------------------------------------------------------
# P0: extract_text — 只取 TextContent.text，忽略 ThinkingContent
# ---------------------------------------------------------------------------


class FakeState:
    def __init__(self, error_message=None):
        self.messages = []
        self.error_message = error_message


class FakeAgent:
    def __init__(self, error_message=None):
        self.state = FakeState(error_message=error_message)


def test_extract_text_only_takes_textcontent():
    """ThinkingContent 不應被提取（不吐 repr 垃圾）。"""
    content = [
        ThinkingContent(thinking="Let me think about this..."),
        TextContent(text="Bull: 核心看漲論點"),
    ]
    assert extract_text(content) == "Bull: 核心看漲論點"


def test_extract_text_thinking_only_returns_empty():
    """只有 thinking 時應回空字串（讓重試機制接手），而非 repr 垃圾。"""
    content = [ThinkingContent(thinking="analyzing...")]
    assert extract_text(content) == ""


def test_extract_text_empty_list():
    assert extract_text([]) == ""


def test_extract_text_non_list_falls_back_to_str():
    assert extract_text("plain string") == "plain string"
    assert extract_text(None) == ""


def test_extract_text_multiple_blocks_concatenated():
    content = [TextContent(text="A"), TextContent(text="B")]
    assert extract_text(content) == "AB"


# ---------------------------------------------------------------------------
# P0: get_agent_error — 正確欄位是 error_message
# ---------------------------------------------------------------------------


def test_get_agent_error_reads_error_message():
    """舊程式讀 state.error（不存在）→ 修正後讀 state.error_message。"""
    agent = FakeAgent(error_message="400 context too long")
    assert get_agent_error(agent) == "400 context too long"


def test_get_agent_error_none_returns_empty():
    agent = FakeAgent(error_message=None)
    assert get_agent_error(agent) == ""


def test_get_agent_error_missing_state_returns_empty():
    class NoStateAgent:
        pass

    assert get_agent_error(NoStateAgent()) == ""
