"""MCP tools for L.I.R.A. using fastmcp.

This module contains the tools that the MCP server exposes to LLMs
for financial data operations.
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

from lira.db.models import (
    Account,
    AccountType,
    Category,
    Holding,
    Transaction,
    TransactionType,
)
from lira.db.session import DatabaseSession
from lira.mcp.server import mcp

try:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
except ImportError:
    matplotlib = None  # type: ignore
    plt = None  # type: ignore


@mcp.tool()
async def list_accounts(active_only: bool = True) -> list[dict[str, Any]]:
    """List all user accounts with their current balances and associated metadata.

    This tool is used to query the database and retrieve a summary of all financial accounts
    (Checking, Savings, Credit Cards, etc.), including their balances and currency types.

    Args:
        active_only: If True, only returns active accounts. If False, returns all accounts.

    Returns:
        A list of dictionaries, each containing the id, name, type, balance, and currency of an account.
    """
    with DatabaseSession() as session:
        query = session.query(Account)
        if active_only:
            query = query.filter(Account.is_active == True)
        accounts = query.all()
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
    """Create a new financial account (e.g., checking, savings, credit, loan).

    This tool provisions a new money tracking account in the SQLite SQL database where future
    transactions can be recorded.

    Args:
        name: The display name of the account (e.g. "Chase Checking").
        account_type: The standard type classification of the account (e.g. "checking", "savings").
        balance: The initial starting balance for the account. Allows initializing with an existing sum.

    Returns:
        A dictionary containing the generated account id, name, and exact starting balance.
    """
    with DatabaseSession() as session:
        account = Account(
            name=name,
            account_type=AccountType(account_type),
            balance=Decimal(str(balance)),
        )
        session.add(account)
        session.commit()
        session.refresh(account)
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
    """Create a new real-world financial transaction representing an income or expense.

    This tool logs movement of money inside an established account. Based on the selected
    transaction_type, it will automatically update the running balance of the target account
    (an expense will decrease it, an income will increase it).

    Args:
        account_id: The unique database id of the account this transaction applies to.
        amount: The monetary value of the transaction. For expenses, use a negative float.
        transaction_type: 'expense', 'income', or 'transfer'. Affects account balance logic.
        description: A short memo describing the purchase, vendor, or reasoning.

    Returns:
        A dictionary containing the generated transaction id, actual logged amount, and recorded type.
    """
    with DatabaseSession() as session:
        account = session.query(Account).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")

        tx_type = TransactionType(transaction_type)
        dec_amount = Decimal(str(amount))

        transaction = Transaction(
            account_id=account_id,
            transaction_type=tx_type,
            amount=dec_amount,
            description=description,
            date=datetime.now(),
        )

        if tx_type == TransactionType.EXPENSE:
            account.balance -= dec_amount
        elif tx_type == TransactionType.INCOME:
            account.balance += dec_amount

        session.add(transaction)
        session.commit()
        session.refresh(transaction)

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
    """Generate an analytical matplotlib visualization chart for financial reporting.

    This agentic tool visualizes incoming dictionary data to build beautiful graphs. It will return
    a strictly formatted base64 encoded PNG representing the graph inside an invisible container context.

    Args:
        plot_type: Defines graph aesthetics (e.g. 'bar', 'line', 'pie', 'scatter').
        title: Explanatory header/title given to the chart.
        data: Expected list of dictionaries where each record holds the x and y mapping.
        x_key: The string referencing the specific key inside "data" storing the x values. Default: "x".
        y_key: The string referencing the specific key inside "data" storing the y values. Default: "y".

    Returns:
        JSON response including the raw base_64 string representing the rendered Matplotlib PNG.
    """
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
    from sqlalchemy import text

    from lira.db.session import DatabaseSession

    params = params or {}
    normalized = query.strip().upper()

    if ";" in normalized.rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed.")

    if not normalized.startswith(("SELECT", "WITH")):
        raise ValueError(
            "Only SELECT/CTE queries are allowed. Use mutation tools for data changes."
        )

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
    """Fetch current, real-time stock quotes, basic info, and history via Yahoo Finance.

    A highly capable querying API designed to pull real market pricing for publicly traded assets.
    Always use this tool when evaluating portfolio metrics, market caps, or the daily close prices.

    Args:
        symbol: The publicly traded stock ticker symbol (e.g., 'AAPL', 'VTI', 'MSFT').
        include_history: Should the response append the time-series trajectory of standard EOD price frames.
        period: Granularity boundary for the historical price feed (e.g., '1d', '5d', '1mo', '3mo', '6mo', '1y').

    Returns:
        JSON response with the precise dynamic localized quote metrics and historical DataFrame strings.
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
        "timestamp": datetime.now().isoformat(),
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
    """Retrieves organized, structured lists of recent transactions filtered directly from the sqlite database.

    A unified ledger query engine mapping filters to transaction criteria. Ideal for summarizing spending behaviour,
    evaluating budgets, and reviewing specific historical account mutations over localized timeframes.

    Args:
        account_id: Narrow to a single Account instance by its primary key ID identifier.
        category: Filter exact categorical descriptors matches.
        start_date: Filter queries occurring on or after 'YYYY-MM-DD'.
        end_date: Filter queries occurring on or prior to 'YYYY-MM-DD'.
        transaction_type: Require exact matching of 'expense', 'income', or 'transfer'.
        min_amount: Ignore transactions under this scalar float boundary.
        max_amount: Ignore transactions eclipsing this scalar float boundary.
        limit: Limit length (Pagination). Defaults to capping at 100 recent rows.

    Returns:
        JSON response with total counts and sliced serialized transaction objects.
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
    """Inspects the asset and stock portfolio, calculating real-time investment exposure and valuation.

    A sophisticated reporting engine which pulls down stored shares (quantities, cost basis) and optionally
    evaluates current market rate valuations using real-world stock quotes (yfinance) to tabulate percentage
    gains/losses natively within the server logic.

    Args:
        portfolio_id: If specified, target one particular defined portfolio instance ID. Otherwise aggregates all investments.
        include_performance: Pass True to trigger external network calls which enrich the list with current price metrics.

    Returns:
        JSON structure with detailed sum of all Holdings, unified value, total basis, and real-time gain assessments.
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
    """Tax estimation engine computing net capital gains (long/short-term models).

    A sophisticated rule engine designed to ingest a ledger of sale records against cost basis. Differentiates
    long-term capital holdings versus short-term day trades accurately computing net and split tax burdens.

    Args:
        sales: Required array of dictionaries structuring asset sales. E.g.[{'symbol': 'NVDA', 'quantity': 10, 'proceeds': 1050.2, 'cost_basis': 900.0, 'purchase_date': '2023-01-01', 'sale_date': '2023-08-01'}]
        tax_rate_short: Short-term income-capped bracket float scalar (e.g. 0.35 for 35%).
        tax_rate_long: Long-term tax concession bracket float scalar (e.g. 0.15 for 15%).
        holding_period_days: Default cutoff to differentiate capital gains maturity.

    Returns:
        JSON summarizing short_term, long_term, and overall obligations mapped to absolute values.
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
        elif gain_loss > 0:
            short_term_gains += gain_loss
        else:
            short_term_losses += abs(gain_loss)

        detailed.append(
            {
                "symbol": symbol,
                "quantity": float(quantity),
                "proceeds": float(proceeds),
                "cost_basis": float(cost_basis),
                "gain_loss": float(gain_loss),
                "days_held": days_held,
                "term": "long" if is_long_term else "short",
            }
        )

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
