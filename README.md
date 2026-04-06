# L.I.R.A.

**L.I.R.A. (LIRA Is Recursive Accounting)** — an AI-native personal finance and investment tracker.

Chat with a local or cloud LLM to log transactions, track investments, query your data in plain English, and approve every mutation before it hits the database.

---

## Features

- Natural language interface (ReAct agentic loop)
- Human-in-the-loop diff engine — preview every INSERT / UPDATE before it runs
- Transaction tracking with categories, payment methods, and secondary categories
- Investment trade records (buy/sell) with P&L
- Real-time web dashboard with WebSocket push
- CLI TUI — run locally or connect to a remote server
- SQLite (single-file, portable)

---

## Quick Start — Local Development

### Prerequisites

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) package manager

```bash
# 1. Clone and install
git clone <repo>
cd LIRA
uv sync

# 2. Copy and edit env vars
cp .env.example .env
# At minimum set LLM_PROVIDER and either OLLAMA_BASE_URL or GROQ_API_KEY

# 3. Run the API server (auto-creates the database on first start)
uv run lira-api
# or with hot-reload for development:
API_RELOAD=true uv run lira-api

# 4. In a second terminal, open the CLI
uv run lira --interactive
```

The web dashboard is at `http://localhost:8000/dashboard`.

On first launch with an empty database, both the CLI and the web chat will prompt you to set your currency, payment methods, and categories.

---

## LLM Providers

Set `LLM_PROVIDER` in your `.env` to choose the backend.

### Ollama (default — runs locally)

```env
LLM_PROVIDER=ollama
LLM_MODEL=gemma3:4b          # any model pulled in Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_KEEP_ALIVE=30m
```

Install Ollama from [ollama.com](https://ollama.com), then pull a model:

```bash
ollama pull gemma3:4b
```

### Groq (cloud — fast, free tier available)

```env
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile   # or llama3-8b-8192, mixtral-8x7b-32768, etc.
GROQ_API_KEY=gsk_...
```

Get a free API key at [console.groq.com](https://console.groq.com).

---

## Self-Hosting with Docker

### 1. Create a `.env` file

```env
# Choose your LLM provider
LLM_PROVIDER=groq           # or ollama
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...

# If using Ollama instead:
# LLM_PROVIDER=ollama
# LLM_MODEL=gemma3:4b
# OLLAMA_BASE_URL=http://ollama:11434
```

### 2. Start the server

**With Groq (no GPU needed):**

```bash
docker compose up -d api
```

**With Ollama on CPU:**

```bash
docker compose --profile cpu up -d
```

**With Ollama on GPU (NVIDIA):**

```bash
docker compose --profile gpu up -d
```

The server starts at `http://<host>:8000`. The database is persisted in `./data/lira.db`.

### 3. Pull a model (Ollama only)

```bash
docker compose exec ollama ollama pull gemma3:4b
```

---

## Connecting the CLI to a Remote Server

Once the server is running (locally or on a home server), connect the CLI from any machine:

```bash
# Option 1: flag
uv run lira --interactive --server http://homeserver:8000

# Option 2: env var
LIRA_API_URL=http://homeserver:8000 uv run lira --interactive
```

Or set it permanently in your local `.env`:

```env
LIRA_API_URL=http://homeserver:8000
```

In remote mode the CLI forwards all messages to the server — no local model or database needed.

The web dashboard at `http://homeserver:8000/dashboard` uses a WebSocket connection and updates in real time whenever the CLI (or anyone else) adds data.

---

## CLI Commands

| Command | Alias | Description |
|---|---|---|
| `/trace` | `/t` | Toggle tool trace display |
| `/show-trace` | `/s` | Show last trace |
| `/reset` | `/r` | Clear session context |
| `/clear` | `/c` | Clear message history |
| `/help` | `/h` | Show available commands |
| `exit` / `quit` | `/q` | Exit the CLI |

---

## Development

```bash
# Run tests
uv run pytest -v

# Lint and format
uv run ruff check src/
uv run ruff format src/

# Type check
uv run mypy src/

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
```

---

## Project Structure

```
src/lira/
├── core/        # Agent loop, LLM layer, config, init
├── db/          # SQLAlchemy models and session
├── mcp/         # MCP server, tools, prompts
├── api/         # FastAPI endpoints + WebSocket
├── cli/         # Textual TUI
└── web/         # Dashboard HTML template
```

---

## Available MCP Tools

`create_transaction`, `get_transactions`, `update_transactions`,
`create_investment`, `get_investments`,
`create_account`, `list_accounts`,
`create_payment_method`, `get_payment_methods`, `update_payment_method_balance`,
`transfer_between_payment_methods`, `record_gain_loss`,
`create_category`, `get_categories`,
`fetch_stock`, `generate_plot`, `create_persistent_plot`,
`execute_sql`, `set_currency`
