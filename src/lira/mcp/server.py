"""MCP server entrypoint for L.I.R.A."""

from __future__ import annotations

from fastmcp import FastMCP

# Create the global FastMCP server instance
mcp = FastMCP("lira-mcp")

# Import tools and prompts so their decorators register with the server
import lira.mcp.tools  # noqa: E402, F401
import lira.mcp.prompts  # noqa: E402, F401


def main() -> None:
    """Run the FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
