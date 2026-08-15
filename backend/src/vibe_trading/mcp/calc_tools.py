"""MCP 計算工具工廠 (Phase 4.4).

把確定性計算層 (quantlib/StackVM/universe) 包裝為與 MCP server call path
相容的工具物件. 簽名對齊 MCP call_tool 的呼叫方式:
    await tool.execute(name=..., args=<Pydantic>, extra=None, callback=None)
"""
from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel

from pi_agent_core import AgentToolResult  # type: ignore[import-untyped]
from pi_agent_core.types import TextContent  # type: ignore[import-untyped]


class CalcTool:
    """同步 fn 包裝為 MCP 可呼叫工具 (回傳 AgentToolResult)."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        params_cls: type[BaseModel],
        fn: Callable[[Any], Any],
    ) -> None:
        self.name = name
        self.label = name
        self.description = description
        self.parameters = params_cls  # list_tools 用 model_fields; call_tool 用 (**args)
        self.execution_mode = None
        self._params_cls = params_cls
        self._fn = fn

    async def execute(
        self,
        name: str,
        args: Any,
        extra: Any = None,
        callback: Any = None,
    ) -> AgentToolResult:
        # args 可能已是 Pydantic 實例 (call_tool 已建構) 或 dict
        params = args if isinstance(args, self._params_cls) else self._params_cls(**args)
        result = self._fn(params)
        text = json.dumps(result, ensure_ascii=False, default=str)
        return AgentToolResult(content=[TextContent(text=text)], details=result)


def make_calc_tool(
    *,
    name: str,
    description: str,
    params_cls: type[BaseModel],
    fn: Callable[[Any], Any],
) -> CalcTool:
    """建構 MCP 計算工具."""
    return CalcTool(name=name, description=description, params_cls=params_cls, fn=fn)
