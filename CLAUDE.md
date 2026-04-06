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
│   ├── core/              # Agentic loop, config, exceptions, LLM logic
│   │   ├── agent.py       # ReAct loop implementation
│   │   ├── config.py      # App configuration (incl. LIRA_API_URL)
│   │   ├── exceptions.py  # Custom exceptions
│   │   └── llm.py         # LLM interaction layer
│   ├── db/                # Database layer
│   │   ├── models.py      # SQLAlchemy models
│   │   └── session.py     # Session management
│   ├── mcp/               # MCP Server
│   │   ├── prompts.py     # MCP prompt implementations
│   │   ├── server.py      # MCP server implementation
│   │   └── tools.py       # MCP tool implementations
│   ├── api/               # FastAPI endpoints
│   │   ├── main.py        # App entry point + WebSocket /ws
│   │   ├── ws.py          # WebSocket connection manager
│   │   └── routes/
│   │       ├── dashboard.py  # Dashboard REST routes (incl. /investments)
│   │       └── plots.py
│   ├── cli/               # CLI interface
│   │   └── console.py     # Rich/Textual TUI (local + remote mode)
│   └── web/               # Web UI templates
├── tests/                 # Test suite
├── docs/                  # Documentation
└── pyproject.toml         # Project configuration
```

## Key Commands

```bash
# Install dependencies
uv sync

# Run development server (port 8001)
uv run fastapi dev src/lira/api/main.py
# or for production / without fastapi-cli:
uv run lira-api

# Run CLI (local agent)
uv run lira --interactive

# Run CLI in remote mode (connects to a running server)
uv run lira --interactive --server http://homeserver:8000
# or via env var:
LIRA_API_URL=http://homeserver:8000 uv run lira --interactive

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

The project is in active development. The following modules have been implemented:

- [x] Package structure with pyproject.toml
- [x] Core agent logic and LLM interaction layer
- [x] Database models and session management
- [x] MCP server, core tools, and prompt implementations
- [x] Basic CLI console app
- [x] API framework integration
- [x] HITL diff engine for mutations
- [x] Web dashboard with real-time WebSocket updates
- [x] Investment tracking (buy/sell trade records)
- [x] CLI remote mode (connects to a running server via HTTP)

## Active Development

See the project board or issues for current tasks. Key areas for development:

1. Expand investment tracking (portfolio aggregation, P&L)
2. Recurring transactions / cron scheduler
3. CSV import / ETL pipeline

## Key Data Models

### Transaction
All fields are mandatory: `account_id`, `amount`, `transaction_type`, `description`,
`merchant`, `category_id`, `secondary_category_id`, `payment_method_id`, `date`.

### Investment
Fields: `date`, `ticker`, `units`, `price_per_unit`, `fees` (default 0),
`trade_type` (buy/sell), `payment_method_id` (optional), `account_id` (optional),
`currency`, `broker`, `exchange`, `notes`.  
Computed: `total_amount = units × price_per_unit + fees`.

## Remote / Container Deployment

L.I.R.A. is designed to run as a container on a home server, accessible via Tailscale
or the local network. Configure the CLI to point at the server:

```bash
# .env on the client machine
LIRA_API_URL=http://homeserver:8000
```

The dashboard (`/dashboard`) connects to `ws://server/ws` for real-time updates —
any transaction or investment added from the CLI (remote mode) immediately refreshes
the dashboard without a page reload.

## Important Notes

- All database operations must use SQLAlchemy ORM (no raw SQL)
- Use Pydantic v2 for all data validation
- Pre-commit hooks run on commit (ruff, mypy, bandit)
- Tests require pytest-asyncio for async functions
