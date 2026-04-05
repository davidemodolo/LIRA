# CLAUDE.md - L.I.R.A. Project Configuration for Claude

This file provides project-specific context for Claude (claude.ai and Claude Code).

## Project Overview

**L.I.R.A. (LIRA Is Recursive Accounting)** is an AI-native personal finance and investment
tracker built with Python. It features an MCP (Model Context Protocol) architecture with an
autonomous ReAct agentic loop.

## Tech Stack

- **Python**: 3.10+
- **Database**: SQLite via SQLAlchemy 2.0
- **API**: FastAPI with Uvicorn
- **CLI**: Rich + Typer
- **Agent Framework**: MCP (Model Context Protocol)
- **AI Integration**: OpenAI/Anthropic compatible
- **Package Manager**: uv

## Project Structure

```
LIRA/
├── src/lira/              # Main package
│   ├── __init__.py        # Package init with version
│   ├── core/              # Agentic loop, tools, exceptions
│   │   ├── agent.py       # ReAct loop implementation
│   │   ├── tools.py       # Tool registry and base classes
│   │   └── exceptions.py  # Custom exceptions
│   ├── db/                # Database layer
│   │   ├── models.py      # SQLAlchemy models
│   │   ├── session.py     # Session management
│   │   └── versioning.py  # Git-like versioning
│   ├── mcp/               # MCP Server
│   │   ├── server.py      # MCP server implementation
│   │   └── tools/         # MCP tool implementations
│   ├── api/               # FastAPI endpoints
│   │   ├── main.py        # App entry point
│   │   └── routes/        # Route handlers
│   ├── cli/               # CLI interface
│   │   └── console.py     # Rich console app
│   └── services/          # Business logic
├── tests/                 # Test suite
├── docs/                  # Documentation
└── pyproject.toml         # Project configuration
```

## Key Commands

```bash
# Install dependencies
uv sync

# Run development server
uv run fastapi dev src/lira/api/main.py

# Run CLI
uv run lira

# Run tests
uv run pytest -v

# Lint and type check
uv run ruff check src/
uv run ruff format src/
uv run mypy src/

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
```

## Coding Standards

- **Formatting**: Ruff formatter (Black-compatible)
- **Linting**: Ruff with strict rules
- **Type Checking**: MyPy with plugin for Pydantic
- **Line Length**: 100 characters
- **Docstrings**: Google style

## Current Status

The project is in early development (v0.1.0-alpha). The following modules are
implemented as stubs:

- [x] Package structure with pyproject.toml
- [x] Core agent skeleton
- [x] Database models (stubs)
- [x] MCP server (stubs)
- [x] CLI console (stubs)
- [x] API routes (stubs)

## Active Development

See the project board or issues for current tasks. Key areas for development:

1. Complete SQLAlchemy models for accounts, transactions, portfolios
2. Implement MCP tool: `execute_sql_select`, `execute_sql_mutate`
3. Implement ReAct agent loop
4. Add HITL diff engine for mutations
5. Create web dashboard templates

## Important Notes

- All database operations must use SQLAlchemy ORM (no raw SQL)
- Use Pydantic v2 for all data validation
- Pre-commit hooks run on commit (ruff, mypy, bandit)
- Tests require pytest-asyncio for async functions
