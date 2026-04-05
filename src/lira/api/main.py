"""FastAPI application for L.I.R.A.

Main entry point for the REST API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lira import __version__
from lira.core.agent import Agent, AgentConfig
from lira.api.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    ChatMessage,
    SimpleQueryRequest,
    SimpleQueryResponse,
)
from lira.mcp.tools import get_portfolio as mcp_get_portfolio
from lira.db.repositories import (
    AccountRepository,
    CategoryRepository,
    TransactionRepository,
)
from lira.db.session import DatabaseSession, close_database, get_session, init_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting L.I.R.A. API v%s", __version__)

    init_database()

    with DatabaseSession() as session:
        category_repo = CategoryRepository(session)
        default_categories = [
            ("Groceries", "🛒", "#4CAF50"),
            ("Dining", "🍽️", "#FF9800"),
            ("Transportation", "🚗", "#2196F3"),
            ("Entertainment", "🎬", "#9C27B0"),
            ("Shopping", "🛍️", "#E91E63"),
            ("Utilities", "💡", "#607D8B"),
            ("Healthcare", "🏥", "#F44336"),
            ("Income", "💰", "#4CAF50"),
            ("Transfer", "🔄", "#9E9E9E"),
        ]
        for name, icon, color in default_categories:
            if not category_repo.get_by_name(name):
                category_repo.create(name=name, icon=icon, color=color)

    logger.info("Database initialized")

    yield

    close_database()
    logger.info("L.I.R.A. API shutdown complete")


app = FastAPI(
    title="L.I.R.A. API",
    description="AI-native personal finance and investment tracker",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_DASHBOARD_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "web" / "templates" / "dashboard.html"
)


def get_db() -> Generator[Session, None, None]:
    """Get database session dependency."""
    yield from get_session()


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle general exceptions."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
        },
    )


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint."""
    return {
        "name": "L.I.R.A. API",
        "version": __version__,
        "description": "AI-native personal finance and investment tracker",
    }


@app.get("/dashboard")
async def dashboard() -> FileResponse:
    """Serve the web dashboard UI."""
    return FileResponse(_DASHBOARD_TEMPLATE_PATH)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


class CreateAccountRequest(BaseModel):
    """Request model for creating an account."""

    name: str = Field(..., min_length=1, max_length=255)
    account_type: str = Field(default="checking")
    currency: str = Field(default="USD", max_length=3)
    balance: float = Field(default=0.0)
    institution: str | None = Field(default=None, max_length=255)


class CreateTransactionRequest(BaseModel):
    """Request model for creating a transaction."""

    account_id: int
    transaction_type: str
    amount: float
    currency: str = Field(default="USD", max_length=3)
    category_id: int | None = None
    description: str | None = None
    merchant: str | None = None
    date: datetime | None = None


class UpdateTransactionRequest(BaseModel):
    """Request model for updating a transaction."""

    category_id: int | None = None
    description: str | None = None
    merchant: str | None = None
    notes: str | None = None
    tags: str | None = None


@app.get("/accounts")
async def list_accounts(
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """List all accounts."""
    repo = AccountRepository(db)
    accounts = repo.get_all(active_only=True)
    return {
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "type": a.account_type.value,
                "balance": float(a.balance),
                "currency": a.currency,
                "institution": a.institution,
                "is_active": a.is_active,
            }
            for a in accounts
        ]
    }


@app.post("/accounts")
async def create_account(
    request: CreateAccountRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new account."""
    repo = AccountRepository(db)
    account = repo.create(
        name=request.name,
        account_type=request.account_type,
        currency=request.currency,
        balance=Decimal(str(request.balance)),
        institution=request.institution,
    )
    return {
        "id": account.id,
        "name": account.name,
        "type": account.account_type.value,
        "balance": float(account.balance),
        "currency": account.currency,
        "is_active": account.is_active,
    }


@app.get("/accounts/{account_id}")
async def get_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get a specific account."""
    repo = AccountRepository(db)
    account = repo.get(account_id)

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "id": account.id,
        "name": account.name,
        "type": account.account_type.value,
        "balance": float(account.balance),
        "currency": account.currency,
        "institution": account.institution,
        "is_active": account.is_active,
        "created_at": account.created_at.isoformat(),
    }


@app.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Delete (deactivate) an account."""
    repo = AccountRepository(db)
    if not repo.delete(account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "deleted"}


@app.get("/transactions")
async def list_transactions(
    account_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List transactions with optional filters."""
    repo = TransactionRepository(db)
    transactions = repo.get_all(
        account_id=account_id,
        limit=limit,
        offset=offset,
    )
    return {
        "transactions": [
            {
                "id": t.id,
                "account_id": t.account_id,
                "type": t.transaction_type.value,
                "amount": float(t.amount),
                "currency": t.currency,
                "description": t.description,
                "merchant": t.merchant,
                "category_id": t.category_id,
                "date": t.date.isoformat(),
                "is_reconciled": t.is_reconciled,
            }
            for t in transactions
        ],
        "count": len(transactions),
        "limit": limit,
        "offset": offset,
    }


@app.post("/transactions")
async def create_transaction(
    request: CreateTransactionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new transaction."""
    repo = TransactionRepository(db)
    transaction = repo.create(
        account_id=request.account_id,
        transaction_type=request.transaction_type,
        amount=Decimal(str(request.amount)),
        currency=request.currency,
        category_id=request.category_id,
        description=request.description,
        merchant=request.merchant,
        date=request.date,
    )
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "type": transaction.transaction_type.value,
        "amount": float(transaction.amount),
        "currency": transaction.currency,
        "date": transaction.date.isoformat(),
    }


@app.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Get a specific transaction."""
    repo = TransactionRepository(db)
    transaction = repo.get(transaction_id)

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "type": transaction.transaction_type.value,
        "amount": float(transaction.amount),
        "currency": transaction.currency,
        "description": transaction.description,
        "merchant": transaction.merchant,
        "category_id": transaction.category_id,
        "date": transaction.date.isoformat(),
        "is_reconciled": transaction.is_reconciled,
    }


@app.patch("/transactions/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    request: UpdateTransactionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a transaction."""
    repo = TransactionRepository(db)
    transaction = repo.update(
        transaction_id,
        category_id=request.category_id,
        description=request.description,
        merchant=request.merchant,
        notes=request.notes,
        tags=request.tags,
    )

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "type": transaction.transaction_type.value,
        "amount": float(transaction.amount),
        "description": transaction.description,
        "merchant": transaction.merchant,
    }


@app.delete("/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: int, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Delete a transaction."""
    repo = TransactionRepository(db)
    if not repo.delete(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"status": "deleted"}


@app.get("/categories")
async def list_categories(
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """List all categories."""
    repo = CategoryRepository(db)
    categories = repo.get_all()
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "icon": c.icon,
                "color": c.color,
            }
            for c in categories
        ]
    }


@app.get("/portfolio")
async def get_portfolio(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get portfolio summary."""
    snapshot = await mcp_get_portfolio()
    return {
        "holdings": snapshot["holdings"],
        "summary": {
            "total_value": snapshot["summary"]["total_value"],
            "total_cost": snapshot["summary"]["total_cost"],
            "total_gain_loss": snapshot["summary"]["total_gain_loss"],
            "total_gain_loss_percent": snapshot["summary"]["total_gain_loss_percent"],
        },
    }


@app.post("/agent/query", response_model=SimpleQueryResponse)
async def agent_query(request: SimpleQueryRequest) -> SimpleQueryResponse:
    """Process a natural language query through the agent (single-turn).

    This endpoint is stateless and does not maintain conversation history.
    For multi-turn conversations, use /agent/chat.

    Args:
        request: Simple query request with text

    Returns:
        Agent response
    """
    config = AgentConfig()
    agent = Agent(config=config)

    response = await agent.run(request.text)

    return SimpleQueryResponse(
        response=response.message,
        state=(
            response.state.value if hasattr(response.state, "value") else response.state
        ),
        iterations=response.iterations,
        data=response.data,
        error=response.error,
        visualizations=response.visualizations,
    )


@app.post("/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    """Process a chat message with full conversation history (stateless).

    This endpoint accepts the complete conversation history and returns
    the updated history with the agent's response. The client is responsible
    for maintaining and sending the conversation history with each request.

    Args:
        request: Chat request with messages history and new message

    Returns:
        Agent response with updated conversation history
    """
    config = AgentConfig()
    agent = Agent(config=config)

    history = [msg.model_dump() for msg in request.messages]

    response = await agent.run(request.new_message, conversation_history=history)

    updated_messages = list(request.messages)
    updated_messages.append(
        ChatMessage(
            role="assistant",
            content=response.message,
            timestamp=datetime.now(timezone.utc),
        )
    )

    return AgentChatResponse(
        response=response.message,
        messages=updated_messages,
        visualizations=response.visualizations,
        iterations=response.iterations,
        error=response.error,
        session_id=request.session_id,
    )


def main() -> None:
    """Run the API server."""
    import uvicorn

    uvicorn.run(
        "lira.api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )


if __name__ == "__main__":
    main()
