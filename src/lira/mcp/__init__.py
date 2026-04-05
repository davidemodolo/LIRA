"""MCP (Model Context Protocol) module for L.I.R.A."""

from fastmcp import FastMCP

# Create the global FastMCP server instance
mcp = FastMCP("lira-mcp")

# Import tools and prompts below so their decorators register them with the server
import lira.mcp.tools
import lira.mcp.prompts

__all__ = [
    "mcp",
]
