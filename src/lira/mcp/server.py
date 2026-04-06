"""MCP server entrypoint for L.I.R.A."""

from __future__ import annotations

import importlib

from fastmcp import FastMCP

# Create the global FastMCP server instance
mcp = FastMCP("lira-mcp")

_registered = False


def register_components() -> None:
    """Import tool and prompt modules so their decorators register with ``mcp``.

    Safe to call multiple times — only the first call performs the imports.
    """
    global _registered
    if _registered:
        return
    importlib.import_module("lira.mcp.tools")
    importlib.import_module("lira.mcp.prompts")
    _registered = True


def main() -> None:
    """Run the FastMCP server."""
    register_components()
    mcp.run()


if __name__ == "__main__":
    main()
