"""MCP (Model Context Protocol) server for Vibe Trading tools.

Exposes all trading tools via MCP protocol, allowing external agents
and IDEs to consume Vibe Trading capabilities.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MCPToolParameter(BaseModel):
    """MCP tool parameter schema."""
    type: str
    description: str
    required: bool = False
    default: Any = None


class MCPTool(BaseModel):
    """MCP tool definition."""
    name: str
    description: str
    parameters: dict[str, MCPToolParameter]


class MCPServer:
    """MCP server that exposes Vibe Trading tools."""

    def __init__(self, tool_context: Any | None = None):
        """Initialize MCP server.

        Args:
            tool_context: Optional ToolContext for tools that need it
                         (e.g., submit_trade_order). If None, trading
                         tools will be excluded.
        """
        self.tool_context: Any = tool_context
        self._tools: dict[str, Any] = {}
        self._initialize_tools()

    def _initialize_tools(self) -> None:
        """Load and register all available tools."""
        # Use absolute import to avoid implicit relative import issues
        from vibe_trading.agents.agent_tools import get_all_tools

        all_tools = get_all_tools()

        for tool in all_tools:
            # Skip trading tools if no tool_context provided
            if tool.name == "submit_trade_order" and self.tool_context is None:
                logger.info(f"Skipping {tool.name} (requires tool_context)")
                continue

            self._tools[tool.name] = tool
            logger.debug(f"Registered MCP tool: {tool.name}")

        # Phase 4.4: 確定性計算工具 (quantlib/StackVM/universe)
        self._add_computation_tools()

        logger.info(f"MCP server initialized with {len(self._tools)} tools")

    def _add_computation_tools(self) -> None:
        """Phase 4.4: 鏡像確定性計算層為 MCP 工具."""
        from pydantic import BaseModel as _BM, Field as _F
        from vibe_trading.mcp.calc_tools import make_calc_tool

        # quantlib_var_calc
        class _VarParams(_BM):
            returns: list = _F(description="收益率序列")
            position_value: float = _F(default=10000.0, description="倉位價值")
            method: str = _F(default="cornish_fisher", description="歷史/參數/Cornish-Fisher/EVT")

        self._tools["quantlib_var_calc"] = make_calc_tool(
            name="quantlib_var_calc",
            description="計算 VaR/CVaR (確定性金融數學, Phase 1.1)",
            params_cls=_VarParams,
            fn=self._calc_var,
        )

        # alpha_stackvm_eval
        class _EvalParams(_BM):
            formula: list = _F(description="公式 AST, 如 [\"ADD\", \"close\", 2]")
            series: dict = _F(default_factory=dict, description="{因子名: 序列}")

        self._tools["alpha_stackvm_eval"] = make_calc_tool(
            name="alpha_stackvm_eval",
            description="StackVM 求值公式 (Phase 2.2)",
            params_cls=_EvalParams,
            fn=self._calc_stackvm,
        )

        # crypto_universe_scan
        class _UniverseParams(_BM):
            tickers: list = _F(description="[{symbol, quote_volume}]")
            top_n: int = _F(default=30, description="回傳數量")

        self._tools["crypto_universe_scan"] = make_calc_tool(
            name="crypto_universe_scan",
            description="動態標的宇宙排名 (Phase 4.2)",
            params_cls=_UniverseParams,
            fn=self._calc_universe,
        )

    # ---- 計算工具實作 (純函式包裝) ----
    def _calc_var(self, args) -> dict:
        import numpy as np
        from vibe_trading.quantlib.risk import calculate_var
        r = calculate_var(
            np.array(args.returns, dtype=float),
            float(args.position_value),
            method=args.method,
        )
        return {"var_95": r.var_95, "var_99": r.var_99, "cvar_95": r.cvar_95,
                "cvar_99": r.cvar_99, "volatility": r.volatility, "method": r.method}

    def _calc_stackvm(self, args) -> dict:
        from vibe_trading.factors.vm import evaluate_formula
        return {"result": evaluate_formula(args.formula, args.series)}

    def _calc_universe(self, args) -> dict:
        from vibe_trading.factors.universe import rank_universe
        return {"ranked": rank_universe(args.tickers, top_n=args.top_n)}

    # ---- Host/Origin guard (DNS-rebinding 防護, Phase 4.4) ----
    ALLOWED_ORIGINS = {"http://localhost", "http://127.0.0.1",
                       "http://localhost:8000", "http://127.0.0.1:8000"}

    def check_origin(self, host: str, origin: str | None = None) -> bool:
        """DNS-rebinding 防護: Host 白名單 + Origin 白名單.

        stdio 模式無 host/origin — 不阻擋; HTTP 模式 (後續) 用此閘門.
        """
        host_ok = host in ("localhost", "127.0.0.1") or host.endswith(".local")
        origin_ok = origin is None or origin in self.ALLOWED_ORIGINS
        return host_ok and origin_ok

    def list_tools(self) -> list[MCPTool]:
        """List all available tools in MCP format.

        Returns:
            List of MCPTool definitions
        """
        mcp_tools = []

        for tool in self._tools.values():
            # Convert Pydantic parameters to MCP format
            parameters = {}
            if hasattr(tool.parameters, "model_fields"):
                for field_name, field_info in tool.parameters.model_fields.items():
                    parameters[field_name] = MCPToolParameter(
                        type=self._python_type_to_json_type(field_info.annotation),
                        description=field_info.description or "",
                        required=field_info.is_required(),
                        default=field_info.default if not field_info.is_required() else None,
                    )

            mcp_tools.append(MCPTool(
                name=tool.name,
                description=tool.description,
                parameters=parameters,
            ))

        return mcp_tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool with given arguments.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments as dictionary

        Returns:
            Tool execution result
        """
        if tool_name not in self._tools:
            return {
                "error": f"Tool not found: {tool_name}",
                "available_tools": list(self._tools.keys()),
            }

        tool = self._tools[tool_name]

        try:
            # Validate and parse arguments using Pydantic model
            params = tool.parameters(**arguments)

            # Execute the tool
            # Note: We pass None for extra and callback as they're not used in MCP context
            result = await tool.execute(
                name=tool_name,
                args=params,
                extra=None,
                callback=None,
            )

            # Convert result to JSON-serializable format
            return self._format_result(result)

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return {
                "error": str(e),
                "tool": tool_name,
            }

    def _python_type_to_json_type(self, python_type: Any) -> str:
        """Convert Python type annotation to JSON schema type."""
        type_str = str(python_type)

        if "str" in type_str:
            return "string"
        elif "int" in type_str:
            return "integer"
        elif "float" in type_str:
            return "number"
        elif "bool" in type_str:
            return "boolean"
        elif "list" in type_str or "List" in type_str:
            return "array"
        elif "dict" in type_str or "Dict" in type_str:
            return "object"
        else:
            return "string"  # Default fallback

    def _format_result(self, result: Any) -> dict[str, Any]:
        """Format tool result for MCP response."""
        # AgentToolResult has content (list of TextContent) and optional details
        if hasattr(result, "content"):
            # Extract text from content blocks
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    texts.append(block.text)

            response = {
                "content": "\n".join(texts),
            }

            # Include details if present
            if hasattr(result, "details") and result.details:
                response["details"] = result.details

            return response
        else:
            # Fallback for unexpected result format
            return {"content": str(result)}


# Global MCP server instance
_mcp_server: MCPServer | None = None


def get_mcp_server(tool_context: Any | None = None) -> MCPServer:
    """Get or create global MCP server instance.

    Args:
        tool_context: Optional ToolContext for trading tools

    Returns:
        MCPServer instance
    """
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer(tool_context=tool_context)
    return _mcp_server


def reset_mcp_server() -> None:
    """Reset the global MCP server instance (for testing)."""
    global _mcp_server
    _mcp_server = None
