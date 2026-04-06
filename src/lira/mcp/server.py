"""MCP server entrypoint for L.I.R.A."""

from __future__ import annotations

from fastmcp import FastMCP

# Create the global FastMCP server instance
mcp = FastMCP("lira-mcp")


def main() -> None:
    """Run the FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
