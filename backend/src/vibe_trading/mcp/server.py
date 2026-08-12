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

        logger.info(f"MCP server initialized with {len(self._tools)} tools")

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
