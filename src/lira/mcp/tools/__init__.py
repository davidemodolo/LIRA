"""MCP tools for L.I.R.A. using fastmcp.

This module contains the tools that the MCP server exposes to LLMs
for financial data operations.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from lira.mcp import mcp


@mcp.tool()
async def execute_sql(
    query: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    params = params or {}

    if query.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "DROP", "ALTER")):
        return {
            "success": False,
            "error": "Only SELECT queries are allowed. Use the mutation tools for data changes.",
        }

    try:
        with DatabaseSession() as session:
            from sqlalchemy import text
            result = session.execute(text(query), params)
            rows = result.fetchall()

            return {
                "success": True,
                "data": [dict(row._mapping) for row in rows],
                "row_count": len(rows),
            }
    except Exception as e:
        logger.exception("SQL execution failed")
        return {
            "success": False,
            "error": str(e),
        }


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
    try:
        import yfinance as yf

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
            result["history"] = hist.to_dict()

        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        logger.exception("Failed to fetch stock %s", symbol)
        return {
            "success": False,
            "error": f"Failed to fetch stock: {e!s}",
        }


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
    from sqlalchemy import and_
    from lira.db.session import DatabaseSession
    from lira.db.models import Transaction, Category

    try:
        with DatabaseSession() as session:
            query = session.query(Transaction)

            if account_id:
                query = query.filter(Transaction.account_id == account_id)

            if category:
                query = query.join(Category).filter(Category.name.ilike(f"%{category}%"))

            if start_date:
                start = datetime.fromisoformat(start_date)
                query = query.filter(Transaction.date >= start)

            if end_date:
                end = datetime.fromisoformat(end_date)
                query = query.filter(Transaction.date <= end)

            if transaction_type:
                query = query.filter(Transaction.transaction_type == transaction_type)

            if min_amount is not None:
                query = query.filter(Transaction.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(Transaction.amount <= max_amount)

            transactions = query.order_by(Transaction.date.desc()).limit(limit).all()

            return {
                "success": True,
                "data": [
                    {
                        "id": t.id,
                        "date": t.date.isoformat(),
                        "type": t.transaction_type.value,
                        "amount": float(t.amount),
                        "currency": t.currency,
                        "description": t.description,
                        "merchant": t.merchant,
                        "account_id": t.account_id,
                        "category": t.category.name if t.category else None,
                    }
                    for t in transactions
                ],
                "count": len(transactions),
            }
    except Exception as e:
        logger.exception("Failed to get transactions")
        return {
            "success": False,
            "error": str(e),
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
    from lira.db.session import DatabaseSession
    from lira.db.models import Holding

    try:
        with DatabaseSession() as session:
            query = session.query(Holding)

            if portfolio_id:
                query = query.filter(Holding.portfolio_id == portfolio_id)

            holdings = query.all()

            total_cost = Decimal("0")
            total_value = Decimal("0")

            result_holdings = []
            for h in holdings:
                current_price = h.current_price or h.average_cost
                value = h.quantity * current_price
                cost = h.quantity * h.average_cost
                gain_loss = value - cost
                gain_loss_pct = (gain_loss / cost * 100) if cost > 0 else Decimal("0")

                total_cost += cost
                total_value += value

                holding_data = {
                    "symbol": h.symbol,
                    "name": h.name,
                    "quantity": float(h.quantity),
                    "average_cost": float(h.average_cost),
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
                "success": True,
                "data": {
                    "holdings": result_holdings,
                    "summary": {
                        "total_holdings": len(result_holdings),
                        "total_cost": float(total_cost),
                        "total_value": float(total_value),
                        "total_gain_loss": float(total_gain_loss),
                        "total_gain_loss_percent": float(total_gain_loss_pct),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }
    except Exception as e:
        logger.exception("Failed to get portfolio")
        return {
            "success": False,
            "error": str(e),
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
        purchase_date = datetime.fromisoformat(sale["purchase_date"])
        sale_date = datetime.fromisoformat(sale["sale_date"])
        holding_days = (sale_date - purchase_date).days

        proceeds = Decimal(str(sale["proceeds"]))
        cost_basis = Decimal(str(sale["cost_basis"]))
        gain_loss = proceeds - cost_basis

        is_long_term = holding_days >= holding_period_days

        if gain_loss >= 0:
            if is_long_term:
                long_term_gains += gain_loss
            else:
                short_term_gains += gain_loss
        elif is_long_term:
            long_term_losses += abs(gain_loss)
        else:
            short_term_losses += abs(gain_loss)

        detailed.append(
            {
                "symbol": sale["symbol"],
                "quantity": sale["quantity"],
                "proceeds": float(proceeds),
                "cost_basis": float(cost_basis),
                "gain_loss": float(gain_loss),
                "holding_days": holding_days,
                "is_long_term": is_long_term,
            }
        )

    net_short_term = short_term_gains - short_term_losses
    net_long_term = long_term_gains - long_term_losses

    short_term_tax = max(Decimal("0"), net_short_term) * Decimal(str(tax_rate_short))
    long_term_tax = max(Decimal("0"), net_long_term) * Decimal(str(tax_rate_long))

    return {
        "success": True,
        "data": {
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
        },
    }
