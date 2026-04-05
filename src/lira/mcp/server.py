"""MCP Server implementation for L.I.R.A.

The MCP server exposes tools and prompts that LLMs can invoke
for financial data operations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class MCPConfig:
    """Configuration for MCP server."""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    tools_enabled: bool = True
    prompts_enabled: bool = True
    resources_enabled: bool = True


@dataclass
class MCPRequest:
    """Incoming MCP request."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResponse:
    """MCP response."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-RPC response format."""
        if self.error:
            return {
                "jsonrpc": self.jsonrpc,
                "id": self.id,
                "error": self.error,
            }
        return {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "result": self.result,
        }


class MCPResource:
    """MCP resource that can be exposed to LLMs."""

    def __init__(
        self,
        uri: str,
        name: str,
        description: str,
        mime_type: str = "application/json",
    ) -> None:
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type

    def to_dict(self) -> dict[str, Any]:
        """Convert to MCP resource format."""
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


class MCPPrompt:
    """MCP prompt template."""

    def __init__(
        self,
        name: str,
        description: str,
        arguments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.arguments = arguments or []

    def to_dict(self) -> dict[str, Any]:
        """Convert to MCP prompt format."""
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }


class MCPMessageKind(str):
    """Message kinds for MCP communication."""

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROMPT_REQUEST = "prompt_request"
    PROMPT_RESPONSE = "prompt_response"
    RESOURCE_READ = "resource_read"


@dataclass
class MCPMessage:
    """MCP message between client and server."""

    kind: str
    payload: dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class MCPServer:
    """Model Context Protocol Server.

    The MCP server provides:
    - Tools: Functions the LLM can call
    - Prompts: Predefined interaction templates
    - Resources: Data sources the LLM can read

    Example:
        ```python
        server = MCPServer(config=MCPConfig(port=8000))

        @server.tool(name="execute_sql", description="Execute SQL query")
        async def execute_sql(query: str):
            return await db.execute(query)

        await server.start()
        ```
    """

    def __init__(
        self,
        config: MCPConfig | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self.config = config or MCPConfig()
        self.tool_registry = tool_registry
        self._tools: dict[str, Callable] = {}
        self._prompts: dict[str, MCPPrompt] = {}
        self._resources: dict[str, MCPResource] = {}
        self._handlers: dict[str, Callable] = {}
        self._running = False

        self._setup_default_handlers()

    def _setup_default_handlers(self) -> None:
        """Setup default method handlers."""
        self._handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
        }

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "prompts": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
            },
            "serverInfo": {
                "name": "lira-mcp",
                "version": "0.1.0",
            },
        }

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request."""
        tools = []
        for name, handler in self._tools.items():
            tool_info = getattr(handler, "_tool_info", {})
            tools.append(
                {
                    "name": name,
                    "description": tool_info.get("description", ""),
                    "inputSchema": tool_info.get("schema", {"type": "object"}),
                }
            )
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        handler = self._tools[tool_name]
        result = await handler(**arguments)

        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result) if not isinstance(result, str) else result,
                }
            ],
            "isError": False,
        }

    async def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle prompts/list request."""
        prompts = [p.to_dict() for p in self._prompts.values()]
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle prompts/get request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self._prompts:
            raise ValueError(f"Unknown prompt: {name}")

        prompt = self._prompts[name]
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": f"Prompt: {prompt.description}",
                    },
                }
            ]
        }

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/list request."""
        resources = [r.to_dict() for r in self._resources.values()]
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")

        if uri not in self._resources:
            raise ValueError(f"Unknown resource: {uri}")

        resource = self._resources[uri]
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": f"Resource: {resource.name}",
                }
            ]
        }

    def tool(
        self, name: str, description: str = "", schema: dict[str, Any] | None = None
    ) -> Callable:
        """Decorator to register a tool.

        Args:
            name: Tool name
            description: Tool description
            schema: JSON schema for tool parameters

        Returns:
            Decorator function

        Example:
            @server.tool(name="fetch_stock", description="Get stock price")
            async def fetch_stock(symbol: str):
                return await yfinance.fetch(symbol)
        """

        def decorator(func: Callable) -> Callable:
            self._tools[name] = func
            func._tool_info = {
                "name": name,
                "description": description,
                "schema": schema or {"type": "object"},
            }
            logger.info("Registered tool: %s", name)
            return func

        return decorator

    def register_prompt(self, prompt: MCPPrompt) -> None:
        """Register a prompt template.

        Args:
            prompt: Prompt to register
        """
        self._prompts[prompt.name] = prompt
        logger.info("Registered prompt: %s", prompt.name)

    def register_resource(self, resource: MCPResource) -> None:
        """Register a resource.

        Args:
            resource: Resource to register
        """
        self._resources[resource.uri] = resource
        logger.info("Registered resource: %s", resource.uri)

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle an incoming MCP request.

        Args:
            request: MCP request

        Returns:
            MCP response
        """
        try:
            method = request.method
            handler = self._handlers.get(method)

            if not handler:
                return MCPResponse(
                    id=request.id,
                    error={
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                )

            result = await handler(request.params)

            return MCPResponse(
                id=request.id,
                result=result,
            )

        except Exception as e:
            logger.exception("Error handling request %s", request.id)
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"Internal error: {e!s}",
                },
            )

    async def start(self) -> None:
        """Start the MCP server."""
        logger.info(
            "Starting MCP server on %s:%d",
            self.config.host,
            self.config.port,
        )
        self._running = True

    async def stop(self) -> None:
        """Stop the MCP server."""
        logger.info("Stopping MCP server")
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running


def create_mcp_server(
    tools: list[Any] | None = None,
    config: MCPConfig | None = None,
) -> MCPServer:
    """Create and configure MCP server with common tools.

    Args:
        tools: List of tool instances to register
        config: Server configuration

    Returns:
        Configured MCP server
    """
    server = MCPServer(config=config)

    from lira.mcp.tools import (
        ExecuteSQLTool,
        FetchStockTool,
        GetPortfolioTool,
        GetTransactionsTool,
    )

    server._tools["execute_sql"] = ExecuteSQLTool()
    server._tools["fetch_stock"] = FetchStockTool()
    server._tools["get_transactions"] = GetTransactionsTool()
    server._tools["get_portfolio"] = GetPortfolioTool()

    return server
