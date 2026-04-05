"""MCP tools for L.I.R.A. using fastmcp.

This module contains the tools that the MCP server exposes to LLMs
for financial data operations.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any
import yfinance as yf

from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

from lira.mcp import mcp
from lira.db.models import Category, Holding, Transaction
from lira.db.repositories import AccountRepository, TransactionRepository
from lira.db.session import DatabaseSession

try:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
except ImportError:
    matplotlib = None
    plt = None


@mcp.tool()
async def list_accounts(active_only: bool = True) -> list[dict[str, Any]]:
    """List accounts with balances and metadata."""
    with DatabaseSession() as session:
        repo = AccountRepository(session)
        accounts = repo.get_all(active_only=active_only)
        return [
            {
                "id": account.id,
                "name": account.name,
                "type": account.account_type.value,
                "balance": float(account.balance),
                "currency": account.currency,
            }
            for account in accounts
        ]

@mcp.tool()
async def create_account(
    name: str,
    account_type: str = "checking",
    balance: float = 0.0,
) -> dict[str, Any]:
    """Create a new account."""
    with DatabaseSession() as session:
        repo = AccountRepository(session)
        account = repo.create(
            name=name,
            account_type=account_type,
            balance=Decimal(str(balance)),
        )
        return {
            "id": account.id,
            "name": account.name,
            "balance": float(account.balance),
        }

@mcp.tool()
async def create_transaction(
    account_id: int,
    amount: float,
    transaction_type: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a new transaction (income or expense)."""
    with DatabaseSession() as session:
        repo = TransactionRepository(session)
        transaction = repo.create(
            account_id=account_id,
            transaction_type=transaction_type,
            amount=Decimal(str(amount)),
            description=description,
        )
        return {
            "id": transaction.id,
            "amount": float(transaction.amount),
            "type": transaction.transaction_type.value,
        }

@mcp.tool()
async def generate_plot(
    plot_type: str,
    title: str,
    data: list[dict[str, Any]],
    x_key: str = "x",
    y_key: str = "y",
) -> dict[str, Any]:
    """Generate a visualization chart and return base64 PNG."""
    if matplotlib is None or plt is None:
        raise RuntimeError("matplotlib is required for plotting")

    fig, ax = plt.subplots(figsize=(10, 6))

    if plot_type == "bar":
        x_vals = [d.get(x_key, "") for d in data]
        y_vals = [float(d.get(y_key, 0)) for d in data]
        ax.bar(x_vals, y_vals, color="#4c72b0")
    elif plot_type == "line":
        x_vals = [d.get(x_key, "") for d in data]
        y_vals = [float(d.get(y_key, 0)) for d in data]
        ax.plot(x_vals, y_vals, marker="o", linestyle="-", color="#4c72b0")
    elif plot_type == "pie":
        labels = [d.get(x_key, "") for d in data]
        sizes = [float(d.get(y_key, 0)) for d in data]
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    elif plot_type == "scatter":
        x_vals = [float(d.get(x_key, 0)) for d in data]
        y_vals = [float(d.get(y_key, 0)) for d in data]
        ax.scatter(x_vals, y_vals, alpha=0.7)
    else:
        plt.close(fig)
        raise ValueError(f"Unsupported plot type: {plot_type}")

    ax.set_title(title, fontsize=14, fontweight="bold")
    if plot_type != "pie":
        ax.set_xlabel(x_key, fontsize=10)
        ax.set_ylabel(y_key, fontsize=10)
        ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    image_buffer = io.BytesIO()
    plt.savefig(image_buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    image_base64 = base64.b64encode(image_buffer.read()).decode("utf-8")
    image_buffer.close()

    return {
        "image_base64": image_base64,
        "plot_type": plot_type,
        "title": title,
    }

@mcp.tool()
async def execute_sql(
    query: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL SELECT query on the database. Use this for read-only queries.

    WARNING: This tool should only be used for SELECT queries.
    Mutations should go through the diff engine.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        Query results
    """
    from lira.db.session import DatabaseSession
    from sqlalchemy import text

    params = params or {}
    normalized = query.strip().upper()

    if ";" in normalized.rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed.")

    if not normalized.startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT/CTE queries are allowed. Use mutation tools for data changes.")

    with DatabaseSession() as session:
        # Use SQLAlchemy's text parameters wrapper for safety
        result = session.execute(text(query), params)
        keys = result.keys()
        return [dict(zip(keys, row, strict=False)) for row in result]

@mcp.tool()
async def fetch_stock(
    symbol: str,
    include_history: bool = False,
    period: str = "1mo",
) -> dict[str, Any]:
    """Fetch current stock quote and basic info from Yahoo Finance.

    Args:
        symbol: Stock ticker symbol (e.g., AAPL, GOOGL)
        include_history: Whether to include historical data
        period: Time period for history (1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max)

    Returns:
        Stock data
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info

    result = {
        "symbol": symbol.upper(),
        "name": info.get("shortName", info.get("longName", symbol)),
        "price": info.get("currentPrice", info.get("regularMarketPrice")),
        "change": info.get("regularMarketChange", 0),
        "change_percent": info.get("regularMarketChangePercent", 0),
        "currency": info.get("currency", "USD"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "dividend_yield": info.get("dividendYield"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),
        "timestamp": datetime.utcnow().isoformat(),
    }

    if include_history:
        hist = ticker.history(period=period)
        result["history"] = [
            {
                "date": date.isoformat(),
                "open": row["Open"],
                "high": row["High"],
                "low": row["Low"],
                "close": row["Close"],
                "volume": row["Volume"],
            }
            for date, row in hist.iterrows()
        ]

    return result

@mcp.tool()
async def get_transactions(
    account_id: int | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    transaction_type: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Get transactions from the database with optional filters.

    Args:
        account_id: Filter by account ID
        category: Filter by category name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        transaction_type: Filter by transaction type
        min_amount: Minimum transaction amount
        max_amount: Maximum transaction amount
        limit: Maximum number of results

    Returns:
        Filtered transactions
    """
    with DatabaseSession() as session:
        query = session.query(Transaction)

        if account_id:
            query = query.filter(Transaction.account_id == account_id)

        if category:
            query = query.join(Category).filter(Category.name.ilike(f"%{category}%"))

        if start_date:
            query = query.filter(Transaction.date >= datetime.fromisoformat(start_date))

        if end_date:
            query = query.filter(Transaction.date <= datetime.fromisoformat(end_date))

        if transaction_type:
            query = query.filter(Transaction.transaction_type == transaction_type)

        if min_amount is not None:
            query = query.filter(Transaction.amount >= min_amount)

        if max_amount is not None:
            query = query.filter(Transaction.amount <= max_amount)

        transactions = query.order_by(Transaction.date.desc()).limit(limit).all()

        formatted_transactions = [
            {
                "id": transaction.id,
                "date": transaction.date.isoformat(),
                "type": transaction.transaction_type.value,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "description": transaction.description,
                "merchant": transaction.merchant,
                "account_id": transaction.account_id,
                "category": transaction.category.name if transaction.category else None,
            }
            for transaction in transactions
        ]

    return {
        "data": formatted_transactions,
        "count": len(formatted_transactions),
    }

@mcp.tool()
async def get_portfolio(
    portfolio_id: int | None = None,
    include_performance: bool = True,
) -> dict[str, Any]:
    """Get current portfolio holdings and performance.

    Args:
        portfolio_id: Specific portfolio ID (default: all)
        include_performance: Include performance metrics

    Returns:
        Portfolio holdings and performance
    """
    with DatabaseSession() as session:
        query = session.query(Holding)
        if portfolio_id:
            query = query.filter(Holding.portfolio_id == portfolio_id)

        holdings = query.all()

        total_cost = Decimal("0")
        total_value = Decimal("0")

        result_holdings: list[dict[str, Any]] = []
        for holding in holdings:
            current_price = holding.current_price or holding.average_cost
            value = holding.quantity * current_price
            cost = holding.quantity * holding.average_cost
            gain_loss = value - cost
            gain_loss_pct = (gain_loss / cost * 100) if cost > 0 else Decimal("0")

            total_cost += cost
            total_value += value

            holding_data: dict[str, Any] = {
                "symbol": holding.symbol,
                "name": holding.name,
                "quantity": float(holding.quantity),
                "average_cost": float(holding.average_cost),
                "current_price": float(current_price),
                "market_value": float(value),
                "cost_basis": float(cost),
                "gain_loss": float(gain_loss),
                "gain_loss_percent": float(gain_loss_pct),
            }

            if include_performance:
                holding_data["unrealized_pnl"] = float(gain_loss)

            result_holdings.append(holding_data)

        total_gain_loss = total_value - total_cost
        total_gain_loss_pct = (
            (total_gain_loss / total_cost * 100) if total_cost > 0 else Decimal("0")
        )

        return {
            "holdings": result_holdings,
            "summary": {
                "total_holdings": len(result_holdings),
                "total_cost": float(total_cost),
                "total_value": float(total_value),
                "total_gain_loss": float(total_gain_loss),
                "total_gain_loss_percent": float(total_gain_loss_pct),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

@mcp.tool()
async def calculate_tax(
    sales: list[dict[str, Any]],
    tax_rate_short: float = 0.35,
    tax_rate_long: float = 0.15,
    holding_period_days: int = 365,
) -> dict[str, Any]:
    """Calculate estimated capital gains tax for realized gains.

    Args:
        sales: List of sales with symbol, quantity, proceeds, purchase_date, sale_date
        tax_rate_short: Tax rate for short-term gains
        tax_rate_long: Tax rate for long-term gains
        holding_period_days: Days to qualify for long-term treatment

    Returns:
        Tax calculation breakdown
    """
    from datetime import datetime
    short_term_gains = Decimal("0")
    long_term_gains = Decimal("0")
    short_term_losses = Decimal("0")
    long_term_losses = Decimal("0")
    detailed = []

    for sale in sales:
        symbol = sale["symbol"]
        quantity = Decimal(str(sale["quantity"]))
        proceeds = Decimal(str(sale["proceeds"]))
        cost_basis = Decimal(str(sale.get("cost_basis", 0)))

        purchase_date = datetime.fromisoformat(sale["purchase_date"]).replace(tzinfo=None)
        sale_date = datetime.fromisoformat(sale["sale_date"]).replace(tzinfo=None)

        days_held = (sale_date - purchase_date).days
        is_long_term = days_held >= holding_period_days

        gain_loss = proceeds - cost_basis

        if is_long_term:
            if gain_loss > 0:
                long_term_gains += gain_loss
            else:
                long_term_losses += abs(gain_loss)
        else:
            if gain_loss > 0:
                short_term_gains += gain_loss
            else:
                short_term_losses += abs(gain_loss)

        detailed.append({
            "symbol": symbol,
            "quantity": float(quantity),
            "proceeds": float(proceeds),
            "cost_basis": float(cost_basis),
            "gain_loss": float(gain_loss),
            "days_held": days_held,
            "term": "long" if is_long_term else "short",
        })

    net_short_term = short_term_gains - short_term_losses
    net_long_term = long_term_gains - long_term_losses

    short_term_tax = max(Decimal("0"), net_short_term) * Decimal(str(tax_rate_short))
    long_term_tax = max(Decimal("0"), net_long_term) * Decimal(str(tax_rate_long))

    return {
        "short_term": {
            "gains": float(short_term_gains),
            "losses": float(short_term_losses),
            "net": float(net_short_term),
            "tax_rate": tax_rate_short,
            "estimated_tax": float(short_term_tax),
        },
        "long_term": {
            "gains": float(long_term_gains),
            "losses": float(long_term_losses),
            "net": float(net_long_term),
            "tax_rate": tax_rate_long,
            "estimated_tax": float(long_term_tax),
        },
        "total_estimated_tax": float(short_term_tax + long_term_tax),
        "detailed": detailed,
    }
