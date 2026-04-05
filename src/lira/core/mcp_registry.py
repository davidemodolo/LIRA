"""Adapter registry exposing MCP tools through the core Tool interface."""

from __future__ import annotations

import json
from typing import Any

from lira.core.tools import Tool, ToolRegistry, ToolResult

class FastMCPAdapterTool(Tool):
    """Core Tool wrapper around an async FastMCP function tool."""

    def __init__(self, fastmcp_tool: Any) -> None:
        self._tool = fastmcp_tool
        self.name = fastmcp_tool.name
        self.description = fastmcp_tool.description
        super().__init__()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            from lira.mcp import mcp
            res = await mcp.call_tool(self.name, kwargs)
            for content in res.content: 
                if content.type == "text":
                    try:
                        data = json.loads(content.text)
                        if isinstance(data, dict) and "success" in data:
                            return ToolResult(
                                success=bool(data.get("success", False)),
                                data=data.get("data", data),
                                error=data.get("error")
                            )
                        return ToolResult(success=True, data=data)
                    except json.JSONDecodeError:
                        return ToolResult(success=True, data=content.text)
            return ToolResult(success=True, data=None)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def get_schema(self) -> dict[str, Any]:
        return self._tool.parameters

def register_mcp_default_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register core Agent tools from FastMCP directly."""
    from lira.mcp import mcp
    import lira.mcp.tools  # Ensure tools are imported

    for component in mcp._local_provider._components.values():
        if hasattr(component, "parameters"):
            registry.register(FastMCPAdapterTool(component))
    return registry
