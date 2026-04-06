# L.I.R.A. Agent Instructions

This file provides guidance to AI coding agents working on the L.I.R.A. project.
When an AI agent reads this project, it should follow these guidelines.

## Project Overview

L.I.R.A. (LIRA Is Recursive Accounting) is an AI-native, agentic personal finance and
investment tracker. It uses an MCP (Model Context Protocol) architecture with a ReAct
(Reason + Act) agentic loop for autonomous financial management.

## Architecture Summary

```
src/lira/
├── core/          # Agentic loop, config (LIRA_API_URL), exceptions, LLM logic
├── db/            # SQLAlchemy models (incl. Investment), session management
├── mcp/           # MCP server, prompts, and tool implementations
├── api/           # FastAPI REST endpoints + WebSocket /ws
│   ├── ws.py      # WebSocket connection manager (real-time push)
│   └── routes/    # dashboard routes (incl. /investments)
├── cli/           # Textual TUI — local agent or remote HTTP mode
├── web/           # Web dashboard (templates + WS client)
└── version.py     # Version information
```

## Key Models

### Investment (new)
Trade-level record for buy/sell operations:
- `date`, `ticker`, `units`, `price_per_unit`, `fees`, `trade_type` (buy/sell)
- `payment_method_id` (FK, optional), `account_id` (FK, optional)
- `currency`, `broker`, `exchange`, `notes`
- Computed property: `total_amount = units × price_per_unit + fees`

### Transaction (updated)
`create_transaction` now accepts an optional `date` parameter (ISO format).
All core fields are mandatory.

## MCP Tools (current)

| Tool | Description |
|------|-------------|
| `create_transaction` | Log an expense/income. Accepts optional `date`. |
| `get_transactions` | Query transactions with filters. |
| `create_investment` | Record a buy/sell trade. |
| `get_investments` | Query investment trades with filters. |
| `create_account` / `list_accounts` | Account management. |
| `create_payment_method` / `get_payment_methods` | Payment methods. |
| `create_category` / `get_categories` | Category management. |
| `fetch_stock` | Real-time stock quotes via yfinance. |
| `generate_plot` | Generate matplotlib chart (base64 PNG). |
| `execute_sql` | Read-only SQL SELECT queries. |
| `set_currency` | Set base currency. |
| `update_payment_method_balance` | Manual balance correction. |
| `transfer_between_payment_methods` | Move funds between methods. |
| `record_gain_loss` | Record gain/loss on a payment method. |
| `create_persistent_plot` | Persist a plot to the dashboard. |

## Real-time Dashboard

The dashboard connects to `ws://<host>/ws`. After any agent tool call completes
(via the `/api/chat` endpoint), the server broadcasts `{"type": "data_changed"}` to
all connected clients, which then call `refreshCurrentSection()` automatically.

## CLI Remote Mode

Set `LIRA_API_URL` env var or use `--server URL` flag. The TUI then forwards all
messages to the remote server's `/api/chat` endpoint (streaming) instead of running
a local agent. HITL confirmations are forwarded to `/api/chat/confirm`.

## Key Design Principles

### 1. Type Safety First
- Always use type hints for function signatures
- Prefer Pydantic models over raw dictionaries
- Run mypy before committing: `uv run mypy src/`

### 2. SQL Injection Prevention
- NEVER use raw SQL strings with user input
- Always use SQLAlchemy's parameterized queries
- Validate and sanitize all external data

### 3. Error Handling
- Use custom exceptions in `lira.core.exceptions`
- Never swallow exceptions silently
- Provide actionable error messages

### 4. Agentic Patterns
- Tools must be stateless and pure functions
- Each tool should have clear input/output schemas
- Document tool purpose and examples in docstrings

### 5. Database Versioning
- All schema changes via Alembic migrations
- Never modify existing migrations
- Test migrations before committing

## Code Style

- Line length: 100 characters
- Use Ruff for formatting: `uv run ruff format`
- Use Ruff for linting: `uv run ruff check`
- Docstrings: Google style with type hints

## Testing Requirements

- All new features require tests
- Unit tests: `tests/unit/`
- Integration tests: `tests/integration/`
- Run tests: `uv run pytest`
- Minimum coverage: 60%

## Commit Guidelines

- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- Keep commits atomic and focused
- Include issue numbers when applicable

## File Organization

### Adding a New Tool (MCP)
1. Create tool in `src/lira/mcp/tools/`
2. Register in tool registry
3. Add type hints and Pydantic schemas
4. Write unit tests
5. Document in tool docstring

### Adding a New Model (Database)
1. Create model in `src/lira/db/models.py`
2. Create migration: `uv run alembic revision --autogenerate -m "desc"`
3. Add repository in `src/lira/db/repositories.py`
4. Write integration tests

### Adding an API Endpoint
1. Define request/response schemas in `src/lira/api/schemas.py`
2. Add route in `src/lira/api/routes/`
3. Register route in `src/lira/api/main.py`
4. Write tests with pytest-httpx

## Dependencies

- Core: FastAPI, SQLAlchemy, Pydantic, httpx
- CLI: Rich, Typer
- Agent: MCP SDK
- Testing: pytest, pytest-asyncio, pytest-cov

## Common Commands

```bash
# Setup
uv sync

# Development
uv run fastapi dev src/lira/api/main.py
uv run lira

# Quality
uv run ruff check src/
uv run ruff format src/
uv run mypy src/

# Testing
uv run pytest
uv run pytest --cov=lira --cov-report=html

# Database
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Docker
docker compose up --build
```

## Important Files

- `pyproject.toml` - Project configuration and dependencies
- `.pre-commit-config.yaml` - Pre-commit hooks
- `src/lira/__init__.py` - Package entry point
- `tests/conftest.py` - Test fixtures and configuration

## Working with the Agent

When implementing features:

1. **Understand the Request**
   - Clarify ambiguous requirements
   - Identify edge cases
   - Consider security implications

2. **Plan the Implementation**
   - Follow existing patterns
   - Use type hints throughout
   - Add docstrings to public APIs

3. **Implement**
   - Write clean, readable code
   - Don't premature optimize
   - Keep functions focused

4. **Test**
   - Write unit tests for logic
   - Write integration tests for APIs
   - Verify edge cases

5. **Verify**
   - Run linter: `uv run ruff check .`
   - Run type checker: `uv run mypy src/`
   - Run tests: `uv run pytest`

## Security Considerations

- Never log sensitive data (API keys, account numbers)
- Validate all user input
- Use parameterized queries
- Follow principle of least privilege
- Keep dependencies updated
