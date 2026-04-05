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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from lira.db.models import (
    Account,
    AccountType,
    Category,
    Holding,
    Transaction,
    TransactionType,
)
from lira.db.session import DatabaseSession, init_database
from lira.mcp.server import mcp

init_database()

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
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


def _resolve_category_name(session: Session, name: str) -> int | None:
    """Resolve a category name (including hierarchical) to its ID.

    Supports formats:
    - "FOOD" (exact match)
    - "food" (case-insensitive)
    - "FOOD > groceries" or "FOOD > bar-restaurant" (hierarchical)

    Args:
        session: Database session
        name: Category name to resolve

    Returns:
        Category ID if found, None otherwise
    """
    name_lower = name.lower().strip()

    exact_match = session.execute(
        select(Category).where(func.lower(Category.name) == name_lower)
    ).scalar_one_or_none()
    if exact_match:
        return exact_match.id

    if " > " in name:
        parts = name.split(" > ")
        if len(parts) == 2:
            parent_name, child_name = parts[0].strip(), parts[1].strip()
            parent = session.execute(
                select(Category).where(func.lower(Category.name) == parent_name.lower())
            ).scalar_one_or_none()
            if parent:
                child = session.execute(
                    select(Category).where(
                        func.lower(Category.name) == child_name.lower(),
                        Category.parent_id == parent.id,
                    )
                ).scalar_one_or_none()
                if child:
                    return child.id

    return None


@mcp.tool()
async def create_transaction(
    account_id: int,
    amount: float,
    transaction_type: str,
    description: str,
    merchant: str,
    category_id: int | None = None,
    category_name: str | None = None,
    secondary_category_id: int | None = None,
    secondary_category_name: str | None = None,
    payment_method_id: int | None = None,
    payment_method_name: str | None = None,
) -> dict[str, Any]:
    """Create a new real-world financial transaction representing an income or expense.

    This tool logs movement of money inside an established account. Based on the selected
    transaction_type, it will automatically update the running balance of the target account
    (an expense will decrease it, an income will increase it).

    Args:
        account_id: The unique database id of the account this applies to (use list_accounts).
        amount: The monetary value of the transaction. Always pass a positive number — the transaction_type determines whether it adds or subtracts from balances.
        transaction_type: 'expense', 'income', or 'transfer'. Affects account balance logic.
        description: A short memo describing the purchase, vendor, or reasoning.
        category_id: The primary category id (use get_categories to find ids).
        category_name: The primary category name (e.g., "FOOD", "FOOD > groceries"). If provided, resolves to id.
        secondary_category_id: The secondary category id for additional categorization.
        secondary_category_name: The secondary category name.
        payment_method_id: The payment method id (use get_payment_methods to find ids).
        payment_method_name: The payment method name (e.g., "Cash", "Debit Card"). If provided, resolves to ID.

    Returns:
        A dictionary containing the generated transaction id, actual logged amount, and recorded type.
    """
    from sqlalchemy import func, select

    from lira.db.models import Category, PaymentMethod

    with DatabaseSession() as session:
        if not account_id:
            first_account = session.query(Account).first()
            if first_account:
                account_id = first_account.id
            else:
                raise ValueError("No accounts found. Please create an account first.")

        account = session.query(Account).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")

        # Resolve category name to ID if provided
        if category_name and not category_id:
            category_id = _resolve_category_name(session, category_name)
            if not category_id:
                raise ValueError(
                    f"Category '{category_name}' not found. You must create the category first."
                )
        if not category_id:
            raise ValueError("category_id or category_name must be provided")

        # Resolve secondary category name to ID if provided
        if secondary_category_name and not secondary_category_id:
            secondary_category_id = _resolve_category_name(
                session, secondary_category_name
            )
            if not secondary_category_id:
                raise ValueError(
                    f"Secondary category '{secondary_category_name}' not found. You must create the category first."
                )
        if not secondary_category_id:
            raise ValueError(
                "secondary_category_id or secondary_category_name must be provided"
            )

        # Resolve payment method name to ID if provided
        payment_method = None
        if payment_method_name and not payment_method_id:
            payment_method = session.execute(
                select(PaymentMethod).where(
                    func.lower(PaymentMethod.name) == payment_method_name.lower()
                )
            ).scalar_one_or_none()
            if payment_method:
                payment_method_id = payment_method.id
            else:
                raise ValueError(f"Payment method '{payment_method_name}' not found")
        elif payment_method_id:
            payment_method = session.query(PaymentMethod).get(payment_method_id)

        if not payment_method_id:
            raise ValueError(
                "payment_method_id or payment_method_name must be provided"
            )

        tx_type = TransactionType(transaction_type)
        # Always store a positive amount; the transaction_type determines direction.
        # Accept negative amounts from LLM but normalise to positive.
        abs_amount = abs(Decimal(str(amount)))

        transaction = Transaction(
            account_id=account_id,
            transaction_type=tx_type,
            amount=abs_amount,
            description=description,
            merchant=merchant,
            category_id=category_id,
            secondary_category_id=secondary_category_id,
            payment_method_id=payment_method_id,
            date=datetime.now(),
        )

        # Update account balance (expense = subtract, income = add)
        if tx_type == TransactionType.EXPENSE:
            account.balance -= abs_amount
        elif tx_type == TransactionType.INCOME:
            account.balance += abs_amount

        # Update payment method balance
        if payment_method:
            if tx_type == TransactionType.EXPENSE:
                payment_method.balance -= abs_amount
            elif tx_type == TransactionType.INCOME:
                payment_method.balance += abs_amount

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
    params: Any = None,
) -> list[dict[str, Any]]:
    """Execute a SQL SELECT query on the database. Use this for read-only queries.

    WARNING: This tool should only be used for SELECT queries.
    Mutations should go through the diff engine.
    Note: To get category names, JOIN `categories` on `transactions.category_id = categories.id` (do NOT use `T.category_name`).

    Args:
        query: SQL query string
        params: Query parameters (dict or None)

    Returns:
        Query results
    """
    from sqlalchemy import text

    from lira.db.session import DatabaseSession

    if params is None:
        params = {}
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
            # Explicit onclause avoids AmbiguousForeignKeysError (two FKs to categories)
            query = query.join(Category, Transaction.category_id == Category.id).filter(
                Category.name.ilike(f"%{category}%")
            )

        if start_date:
            query = query.filter(Transaction.date >= datetime.fromisoformat(start_date))

        if end_date:
            query = query.filter(Transaction.date <= datetime.fromisoformat(end_date))

        if transaction_type:
            query = query.filter(
                Transaction.transaction_type == TransactionType(transaction_type)
            )

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

        purchase_date = datetime.fromisoformat(sale["purchase_date"]).replace(
            tzinfo=None
        )
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


@mcp.tool()
async def set_currency(currency: str) -> dict[str, Any]:
    """Set the user's base currency.

    This should be called during first-run setup when the user provides their preferred currency.

    Args:
        currency: The currency code (e.g., "USD", "EUR", "GBP")

    Returns:
        Dictionary with success status and the set currency.
    """
    from lira.core.init import set_currency as set_currency_func

    set_currency_func(currency.upper())
    return {"success": True, "currency": currency.upper()}


@mcp.tool()
async def get_payment_methods() -> list[dict[str, Any]]:
    """Get all available payment methods.

    Returns:
        A list of dictionaries containing payment method id, name, and is_default status.
    """
    from lira.core.init import get_payment_methods as get_pm_func

    methods = get_pm_func()
    return [
        {
            "id": pm.id,
            "name": pm.name,
            "is_default": pm.is_default,
        }
        for pm in methods
    ]


@mcp.tool()
async def create_payment_method(
    name: str, is_default: bool = False, balance: float = 0.0
) -> dict[str, Any]:
    """Create a new payment method.

    Args:
        name: The name of the payment method (e.g., "Cash", "Debit Card", "American Express").
        is_default: Whether this should be the default payment method.
        balance: Initial balance for this payment method (default 0).

    Returns:
        Dictionary with the created payment method id, name, and balance.
    """
    from lira.core.init import create_payment_method as create_pm_func

    pm = create_pm_func(name, is_default=is_default, balance=balance)
    return {
        "id": pm.id,
        "name": pm.name,
        "balance": float(pm.balance),
        "is_default": pm.is_default,
    }


@mcp.tool()
async def get_categories() -> list[dict[str, Any]]:
    """Get all available transaction categories with their hierarchy.

    Returns:
        A list of category dictionaries with id, name, and parent_id for hierarchy.
    """
    from lira.core.init import get_categories as get_cats_func

    categories = get_cats_func()
    return [
        {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
        }
        for cat in categories
    ]


@mcp.tool()
async def create_category(
    name: str, parent_id: int | str | None = None, is_system: bool = False
) -> dict[str, Any]:
    """Create a new transaction category.

    Categories should be structured hierarchically. E.g. "FOOD" as parent, and "groceries" as child constraint.

    Args:
        name: The name of the category (e.g. "FOOD", "groceries")
        parent_id: Optional parent category ID (integer) or parent category name (string)
        is_system: Whether this is a system category

    Returns:
        A dictionary containing the generated category id, name, and parent_id.
    """
    from sqlalchemy import func, select
    from lira.db.models import Category
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        # Resolve parent_id: accept either an integer ID or a category name string
        resolved_parent_id: int | None = None
        if parent_id is not None:
            if isinstance(parent_id, int):
                resolved_parent_id = parent_id
            else:
                try:
                    resolved_parent_id = int(parent_id)
                except (ValueError, TypeError):
                    # Treat as a name — look up the parent by name
                    parent_cat = session.execute(
                        select(Category).where(func.lower(Category.name) == str(parent_id).lower())
                    ).scalar_one_or_none()
                    if parent_cat:
                        resolved_parent_id = parent_cat.id

        # Check if category already exists to avoid duplicates
        existing = session.execute(
            select(Category).where(func.lower(Category.name) == name.lower())
        ).scalar_one_or_none()

        if existing:
            return {
                "id": existing.id,
                "name": existing.name,
                "parent_id": existing.parent_id,
            }

        category = Category(
            name=name,
            parent_id=resolved_parent_id,
            is_system=is_system,
        )
        session.add(category)
        session.commit()
        return {
            "id": category.id,
            "name": category.name,
            "parent_id": category.parent_id,
        }


@mcp.tool()
async def update_transactions(
    category_id: int | None = None,
    description_pattern: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Update multiple transactions in bulk based on filters.

    This tool allows mass updates to transactions, useful for fixing categorization
    or applying changes to historical data. Use dry_run=True first to preview changes.

    Args:
        category_id: New category_id to set for matching transactions.
        description_pattern: SQL LIKE pattern to match against description (e.g., "%pizza%").
        start_date: Start date filter in ISO format (YYYY-MM-DD).
        end_date: End date filter in ISO format (YYYY-MM-DD).
        dry_run: If True, only return matching transactions without applying changes.

    Returns:
        Dictionary with count of matched transactions and details.
    """
    from datetime import datetime

    with DatabaseSession() as session:
        query = session.query(Transaction)

        if description_pattern:
            query = query.filter(Transaction.description.like(description_pattern))

        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            query = query.filter(Transaction.date >= start_dt)

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            query = query.filter(Transaction.date <= end_dt)

        matching = query.all()

        if dry_run:
            return {
                "matched_count": len(matching),
                "dry_run": True,
                "transactions": [
                    {
                        "id": t.id,
                        "date": t.date.isoformat(),
                        "description": t.description,
                        "amount": float(t.amount),
                        "category_id": t.category_id,
                    }
                    for t in matching[:100]
                ],
            }

        if category_id is not None:
            for t in matching:
                t.category_id = category_id

        return {
            "updated_count": len(matching),
            "dry_run": False,
            "category_id": category_id,
        }


@mcp.tool()
async def get_payment_method_balances() -> list[dict[str, Any]]:
    """Get all payment methods with their balances.

    Returns:
        A list of dictionaries containing payment method id, name, and balance.
    """
    from lira.core.init import get_payment_methods as get_pm_func

    methods = get_pm_func()
    return [
        {
            "id": pm.id,
            "name": pm.name,
            "balance": float(pm.balance),
            "is_default": pm.is_default,
        }
        for pm in methods
    ]


@mcp.tool()
async def update_payment_method_balance(
    payment_method_name: str, new_balance: float
) -> dict[str, Any]:
    """Set the balance of a payment method directly.

    Use this when there's an inconsistency and you need to manually set the balance
    (e.g., "set my Cash balance to $450").

    Args:
        payment_method_name: The name of the payment method (use get_payment_methods to see available names).
        new_balance: The new balance value to set.

    Returns:
        Dictionary with success status, payment method name, old balance, and new balance.
    """
    from lira.core.init import update_payment_method_balance as update_balance_func

    return update_balance_func(payment_method_name, new_balance)


@mcp.tool()
async def transfer_between_payment_methods(
    from_method: str, to_method: str, amount: float
) -> dict[str, Any]:
    """Transfer money between payment methods.

    Use this when the user says things like "I moved $50 from Cash to Debit Card".

    Args:
        from_method: Source payment method name (use get_payment_methods to see available names).
        to_method: Destination payment method name.
        amount: Amount to transfer.

    Returns:
        Dictionary with success status, transfer details, and new balances.
    """
    from lira.core.init import transfer_between_payment_methods as transfer_func

    return transfer_func(from_method, to_method, amount)


@mcp.tool()
async def record_gain_loss(payment_method_name: str, amount: float) -> dict[str, Any]:
    """Record a gain or loss for a payment method.

    Use this when the user says things like "I gained $500 in my Cash account"
    or "I lost $100 from my Debit Card".

    Args:
        payment_method_name: The name of the payment method.
        amount: Positive for gain, negative for loss.

    Returns:
        Dictionary with success status, amount, old balance, and new balance.
    """
    from lira.core.init import gain_loss_payment_method as gain_loss_func

    return gain_loss_func(payment_method_name, amount)


@mcp.tool()
async def create_persistent_plot(
    name: str,
    plot_type: str = "bar",
    title: str = "",
    x_key: str = "x",
    y_key: str = "y",
) -> dict[str, Any]:
    """Create a persistent plot on the dashboard.

    Use this when the user says "add to my dashboard a persistent plot about..."
    The plot will be saved to the database and shown on the dashboard.

    Args:
        name: Name/title for the plot.
        plot_type: Type of plot ('bar', 'line', 'pie', 'scatter').
        title: Display title for the plot.
        x_key: Key to use for x-axis values.
        y_key: Key to use for y-axis values.

    Returns:
        Dictionary with success status and plot details.
    """
    from lira.core.init import create_persistent_plot as create_plot_func

    return create_plot_func(name, plot_type, title, x_key, y_key)
