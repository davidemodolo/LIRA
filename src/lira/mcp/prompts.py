"""MCP prompts for L.I.R.A."""

from lira.mcp.server import mcp

@mcp.prompt()
def financial_analysis(query: str) -> str:
    """A prompt to analyze financial data."""
    return f"Please analyze this financial query using the available tools: {query}"
