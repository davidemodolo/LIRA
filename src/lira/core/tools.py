"""Tool system for L.I.R.A. MCP integration.

Tools are stateless functions that the agent can call to interact with
external systems (database, APIs, etc.).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class ToolMetadata:
    """Metadata describing a tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    returns: dict[str, Any] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    category: str = "general"
    danger_level: int = Field(
        default=0,
        description="0=safe, 1=read-only, 2=modifying, 3=destructive",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "examples": self.examples,
            "category": self.category,
            "danger_level": self.danger_level,
        }


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


class Tool(ABC):
    """Base class for L.I.R.A. tools.

    Tools are the building blocks of the MCP system. Each tool represents
    a capability that the agent can invoke.

    Example:
        ```python
        class ExecuteSQLTool(Tool):
            name = "execute_sql"
            description = "Execute a SQL query on the database"

            async def execute(self, query: str, params: dict | None = None) -> ToolResult:
                # Implementation
                return ToolResult(success=True, data=results)
        ```
    """

    name: str = ""
    description: str = ""
    metadata: ToolMetadata | None = None

    def __init__(self) -> None:
        if self.metadata is None:
            self.metadata = ToolMetadata(
                name=self.name,
                description=self.description,
            )

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            ToolResult with execution outcome
        """
        ...

    @abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """Get JSON schema for tool parameters.

        Returns:
            JSON schema describing tool parameters
        """
        ...

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and sanitize tool input.

        Args:
            data: Raw input data

        Returns:
            Validated and sanitized data

        Raises:
            ValueError: If validation fails
        """
        return data


class ToolRegistry:
    """Registry for managing available tools.

    The registry maintains a collection of tools and provides
    lookup and execution capabilities.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._categories: dict[str, list[str]] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register
        """
        if not tool.name:
            raise ValueError("Tool must have a name")

        if tool.name in self._tools:
            logger.warning("Overriding existing tool: %s", tool.name)

        self._tools[tool.name] = tool

        category = tool.metadata.category if tool.metadata else "general"
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(tool.name)

        logger.info("Registered tool: %s (category: %s)", tool.name, category)

    def unregister(self, name: str) -> bool:
        """Unregister a tool.

        Args:
            name: Tool name to remove

        Returns:
            True if tool was removed, False if not found
        """
        if name not in self._tools:
            return False

        tool = self._tools.pop(name)
        category = tool.metadata.category if tool.metadata else "general"
        if category in self._categories:
            self._categories[category].remove(name)

        logger.info("Unregistered tool: %s", name)
        return True

    def get(self, name: str) -> Tool | None:
        """Get a tool by name.

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[Tool]:
        """List tools in a category.

        Args:
            category: Category name

        Returns:
            List of tools in category
        """
        tool_names = self._categories.get(category, [])
        return [self._tools[name] for name in tool_names if name in self._tools]

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools.

        Returns:
            List of tool schemas
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.get_schema(),
                "metadata": (tool.metadata.to_dict() if hasattr(tool.metadata, "to_dict") else {}),
            }
            for tool in self._tools.values()
        ]


def create_safe_tool(
    tool_name: str,
    tool_description: str,
    func: Callable[..., Any],
    schema: dict[str, Any],
    danger_level: int = 1,
) -> Tool:
    """Create a tool from a function.

    Args:
        tool_name: Tool name
        tool_description: Tool description
        func: Function to wrap
        schema: JSON schema for parameters
        danger_level: Safety level (0=safe, 3=destructive)

    Returns:
        Tool instance wrapping the function
    """

    class FunctionTool(Tool):
        name = tool_name
        description = tool_description
        metadata = ToolMetadata(
            name=tool_name,
            description=tool_description,
            danger_level=danger_level,
        )

        async def execute(self, **kwargs: Any) -> ToolResult:
            try:
                result = func(**kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                return ToolResult(success=True, data=result)
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        def get_schema(self) -> dict[str, Any]:
            return schema

    return FunctionTool()
