"""FastAPI application for L.I.R.A.

Main entry point for the REST API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lira import __version__
from lira.db.session import close_database, init_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting L.I.R.A. API v%s", __version__)

    init_database()
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


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/accounts")
async def list_accounts() -> dict[str, list[dict[str, Any]]]:
    """List all accounts."""
    from lira.db.models import Account
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        accounts = session.query(Account).all()
        return {
            "accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.account_type.value,
                    "balance": float(a.balance),
                    "currency": a.currency,
                    "is_active": a.is_active,
                }
                for a in accounts
            ]
        }


@app.get("/accounts/{account_id}")
async def get_account(account_id: int) -> dict[str, Any]:
    """Get a specific account."""
    from lira.db.models import Account
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        account = session.query(Account).filter_by(id=account_id).first()

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
        }


@app.get("/transactions")
async def list_transactions(
    account_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List transactions with optional filters."""
    from lira.db.models import Transaction
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        query = session.query(Transaction)

        if account_id:
            query = query.filter(Transaction.account_id == account_id)

        total = query.count()
        transactions = query.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()

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
                    "date": t.date.isoformat(),
                }
                for t in transactions
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    """Get portfolio summary."""
    from lira.db.models import Holding
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        holdings = session.query(Holding).all()

        total_value = 0.0
        total_cost = 0.0

        holding_list = []
        for h in holdings:
            value = float(h.quantity * (h.current_price or h.average_cost))
            cost = float(h.quantity * h.average_cost)
            total_value += value
            total_cost += cost

            holding_list.append(
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "quantity": float(h.quantity),
                    "average_cost": float(h.average_cost),
                    "current_price": float(h.current_price or h.average_cost),
                    "market_value": value,
                    "gain_loss": value - cost,
                    "gain_loss_percent": ((value - cost) / cost * 100) if cost else 0,
                }
            )

        return {
            "holdings": holding_list,
            "summary": {
                "total_value": total_value,
                "total_cost": total_cost,
                "total_gain_loss": total_value - total_cost,
                "total_gain_loss_percent": (
                    ((total_value - total_cost) / total_cost * 100) if total_cost else 0
                ),
            },
        }


@app.post("/agent/query")
async def agent_query(message: dict[str, str]) -> dict[str, Any]:
    """Process a natural language query through the agent.

    Args:
        message: Dict with 'text' key containing the query

    Returns:
        Agent response
    """
    from lira.core.agent import Agent, AgentConfig

    text = message.get("text", "")

    if not text:
        raise HTTPException(status_code=400, detail="Query text is required")

    config = AgentConfig()
    agent = Agent(config=config)

    response = await agent.run(text)

    return {
        "response": response.message,
        "state": response.state.value,
        "iterations": response.iterations,
        "data": response.data,
        "error": response.error,
    }


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
