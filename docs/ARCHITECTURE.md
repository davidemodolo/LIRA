# L.I.R.A. Architecture

Detailed technical architecture documentation for L.I.R.A.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENTS                                  │
├─────────────────┬─────────────────┬─────────────────────────────┤
│   CLI (Rich)    │  Web Dashboard  │     MCP Client (LLM)       │
│                 │                 │                             │
│  - Interactive  │  - HTMX/React   │  - Natural Language         │
│    Commands     │  - Charts       │    Queries                  │
│  - Rich UI      │  - Diff View    │  - Tool Calls               │
└────────┬────────┴────────┬────────┴────────────┬────────────────┘
         │                 │                     │
         └─────────────────┴───────────────────┘
                           │
                    ┌──────┴──────┐
                    │   FastAPI   │
                    │    Server   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────┴────┐      ┌─────┴────┐     ┌─────┴────┐
    │  REST   │      │   MCP    │     │  Agent   │
    │  Routes │      │  Server  │     │   Loop   │
    └────┬────┘      └─────┬────┘     └─────┬────┘
         │                 │                 │
         │          ┌──────┴──────┐         │
         │          │   Tools     │         │
         │          │ Registry    │         │
         │          └──────┬──────┘         │
         │                 │                 │
         └────────┬────────┴────────┬────────┘
                  │                 │
           ┌──────┴──────┐   ┌─────┴─────┐
           │   SQLite    │   │ External   │
           │  Database   │   │   APIs     │
           │             │   │ (yfinance) │
           └─────────────┘   └─────────────┘
```

## Module Structure

### 1. `lira.core` - Agentic Core

The core module contains the ReAct agent implementation and tool system.

#### `agent.py`
- **Purpose**: ReAct loop implementation for autonomous reasoning
- **Key Classes**:
  - `Agent`: Main agent class with reasoning and action capabilities
  - `AgentConfig`: Configuration for agent behavior
  - `AgentState`: Enum for tracking agent execution states
- **Key Features**:
  - Self-correction on SQL errors
  - Multi-step reasoning with iteration limits
  - LLM provider abstraction

#### `tools.py`
- **Purpose**: Tool registry and base tool classes
- **Key Classes**:
  - `Tool`: Abstract base for all MCP tools
  - `ToolRegistry`: Central registry for available tools
  - `ToolMetadata`: Metadata for tool documentation
- **Key Functions**:
  - `create_safe_tool()`: Factory for creating tools from functions

#### `exceptions.py`
- Custom exception hierarchy for consistent error handling

### 2. `lira.db` - Database Layer

SQLAlchemy models and session management.

#### `models.py`
- **Core Models**:
  - `Account`: Financial accounts (checking, savings, credit, etc.)
  - `Transaction`: Individual financial transactions
  - `Category`: Transaction categories with hierarchy
  - `Portfolio`: Investment portfolio container
  - `Holding`: Current security positions
  - `Trade`: Trade execution records
  - `Lot`: Tax lots for cost basis tracking
  - `LotSale`: Links lots to sales for tax reporting

#### `session.py`
- **Database Management**:
  - `init_database()`: Initialize SQLAlchemy engine
  - `DatabaseSession()`: Context manager for sessions
  - SQLite optimizations (WAL mode, foreign keys)

#### `versioning.py`
- **Git-like Versioning**:
  - Event sourcing for change tracking
  - Snapshots for point-in-time recovery
  - Tags for named checkpoints
  - Diff engine for change visualization

### 3. `lira.mcp` - Model Context Protocol

MCP server implementation for LLM tool integration.

#### `server.py`
- **MCP Server**:
  - JSON-RPC 2.0 protocol implementation
  - Tools, prompts, and resources exposure
  - Request routing and error handling

#### `tools/` - MCP Tool Implementations
- `ExecuteSQLTool`: Read-only SQL execution
- `FetchStockTool`: Yahoo Finance integration
- `GetTransactionsTool`: Transaction queries
- `GetPortfolioTool`: Portfolio holdings
- `CalculateTaxTool`: Capital gains estimation

### 4. `lira.api` - REST API

FastAPI-based REST endpoints.

#### `main.py`
- Application entry point with lifespan management
- Health check and root endpoints
- CORS middleware configuration

#### `routes/`
- `accounts.py`: Account CRUD operations
- `transactions.py`: Transaction queries and mutations
- `portfolio.py`: Portfolio management
- `agent.py`: Agent query endpoint

### 5. `lira.cli` - Command Line Interface

Rich-based terminal interface.

#### `console.py`
- **Commands**:
  - `lira status`: System status overview
  - `lira accounts`: Account listing
  - `lira portfolio`: Portfolio management
  - Interactive chat mode

### 6. `lira.services` - Business Logic

Domain-specific business logic layer.

#### `portfolio.py`
- Buy/sell order execution
- Cost basis tracking (FIFO)
- Performance calculations
- Price updates

#### `analytics.py`
- Spending analysis by category
- Monthly summaries
- Trend detection
- Anomaly detection

## Data Flow

### Transaction Entry Flow
```
User Input → CLI/API → Agent → HITL Diff Engine → User Confirmation → DB Commit
```

### Agent Query Flow
```
Natural Language → ReAct Loop → Tool Selection → Tool Execution → Response
                    ↓
              Self-correction (on error)
```

### Portfolio Update Flow
```
Market Data Request → yfinance API → Price Update → Performance Recalc
```

## Security Considerations

### SQL Injection Prevention
- All queries use SQLAlchemy ORM
- Parameterized queries via `session.execute(query, params)`
- Raw SQL only for admin operations

### Data Protection
- No API keys logged
- Sensitive fields masked in errors
- Input validation on all endpoints

### Access Control
- Account-level isolation (future)
- Role-based permissions (future)

## Extensibility

### Adding a New Tool
1. Create tool class inheriting from `Tool`
2. Register in MCP server or tool registry
3. Add tests in `tests/unit/`
4. Document with examples

### Adding a New Model
1. Define in `lira/db/models.py`
2. Create Alembic migration
3. Add repository methods
4. Write integration tests

### Adding a New API Endpoint
1. Define schemas in `lira/api/schemas.py`
2. Add route in appropriate module
3. Register in `main.py`
4. Test with pytest-httpx

## Performance Considerations

### Database
- SQLite with WAL mode for concurrent reads
- Indexes on frequently queried columns
- Batch inserts for CSV imports

### Agent
- Iteration limits to prevent infinite loops
- Async tool execution
- Connection pooling for external APIs

### CLI
- Rich terminal output optimization
- Pagination for large result sets

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Model creation and validation
- Service business logic
- Tool execution
- Agent reasoning (mocked dependencies)

### Integration Tests (`tests/integration/`)
- API endpoint testing
- Database operations
- End-to-end workflows

### Test Fixtures
- In-memory SQLite database
- Sample data factories
- Mock LLM providers
