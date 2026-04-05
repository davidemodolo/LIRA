"""Dashboard API routes."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from lira.db.models import (
    Account,
    AuditLog,
    Category,
    DashboardPlot,
    Holding,
    PaymentMethod,
    Settings,
    Transaction,
    TransactionType,
)
from lira.db.session import DatabaseSession, init_database

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class TransactionFilter(BaseModel):
    """Transaction filter parameters."""

    account_id: int | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    transaction_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int = 100
    offset: int = 0


class PlotConfig(BaseModel):
    """Plot configuration."""

    plot_type: str
    title: str
    x_key: str = "x"
    y_key: str = "y"
    config: dict[str, Any] = {}


class PlotData(BaseModel):
    """Plot data response."""

    id: int
    name: str
    plot_type: str
    title: str
    data: list[dict[str, Any]]


init_database()


@router.get("/summary")
async def get_summary() -> dict[str, Any]:
    """Get summary data for dashboard."""
    with DatabaseSession() as session:
        accounts = session.execute(select(Account)).scalars().all()
        payment_methods = session.execute(select(PaymentMethod)).scalars().all()
        transactions = session.execute(select(Transaction)).scalars().all()
        holdings = session.execute(select(Holding)).scalars().all()
        categories = session.execute(select(Category)).scalars().all()

        total_payment_balance = sum(pm.balance for pm in payment_methods)
        total_investments = sum(float(h.quantity * (h.current_price or 0)) for h in holdings)

        # Calculate total expenses (negative expenses)
        total_expenses = sum(
            abs(t.amount) for t in transactions if t.transaction_type == TransactionType.EXPENSE
        )
        total_income = sum(
            t.amount for t in transactions if t.transaction_type == TransactionType.INCOME
        )

        net_worth = total_payment_balance + Decimal(str(total_investments))

        return {
            "total_accounts": len(accounts),
            "total_transactions": len(transactions),
            "total_categories": len(categories),
            "total_payment_methods": len(payment_methods),
            "total_holdings": len(holdings),
            "payment_balance": float(total_payment_balance),
            "investments": total_investments,
            "total_income": float(total_income),
            "total_expenses": float(total_expenses),
            "net_worth": float(net_worth),
        }


@router.get("/accounts")
async def get_accounts(active_only: bool = True) -> list[dict[str, Any]]:
    """Get all accounts."""
    with DatabaseSession() as session:
        query = select(Account)
        if active_only:
            query = query.filter(Account.is_active == True)
        accounts = session.execute(query).scalars().all()

        return [
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


@router.get("/payment-methods")
async def get_payment_methods() -> list[dict[str, Any]]:
    """Get all payment methods with balances."""
    with DatabaseSession() as session:
        methods = session.execute(select(PaymentMethod)).scalars().all()

        return [
            {
                "id": pm.id,
                "name": pm.name,
                "balance": float(pm.balance),
                "is_default": pm.is_default,
            }
            for pm in methods
        ]


@router.get("/transactions")
async def get_transactions(
    account_id: int | None = Query(None),
    category_id: int | None = Query(None),
    payment_method_id: int | None = Query(None),
    transaction_type: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
) -> dict[str, Any]:
    """Get transactions with filters."""
    from sqlalchemy.orm import joinedload

    with DatabaseSession() as session:
        query = select(Transaction).options(
            joinedload(Transaction.category),
            joinedload(Transaction.secondary_category),
            joinedload(Transaction.payment_method),
            joinedload(Transaction.account),
        )

        if account_id:
            query = query.filter(Transaction.account_id == account_id)
        if category_id:
            query = query.filter(Transaction.category_id == category_id)
        if payment_method_id:
            query = query.filter(Transaction.payment_method_id == payment_method_id)
        if transaction_type:
            query = query.filter(Transaction.transaction_type == TransactionType(transaction_type))
        if start_date:
            start_dt = datetime.fromisoformat(start_date)
            query = query.filter(Transaction.date >= start_dt)
        if end_date:
            end_dt = datetime.fromisoformat(end_date)
            query = query.filter(Transaction.date <= end_dt)

        # Count matching rows without the joinedload (cleaner count)
        count_q = select(func.count(Transaction.id))
        if account_id:
            count_q = count_q.filter(Transaction.account_id == account_id)
        if category_id:
            count_q = count_q.filter(Transaction.category_id == category_id)
        if payment_method_id:
            count_q = count_q.filter(Transaction.payment_method_id == payment_method_id)
        if transaction_type:
            count_q = count_q.filter(Transaction.transaction_type == TransactionType(transaction_type))
        if start_date:
            count_q = count_q.filter(Transaction.date >= datetime.fromisoformat(start_date))
        if end_date:
            count_q = count_q.filter(Transaction.date <= datetime.fromisoformat(end_date))
        total = session.execute(count_q).scalar() or 0

        query = query.order_by(Transaction.date.desc()).offset(offset).limit(limit)
        transactions = session.execute(query).unique().scalars().all()

        def category_label(t: Transaction) -> str:
            if t.category and t.secondary_category and t.category_id != t.secondary_category_id:
                return f"{t.category.name} > {t.secondary_category.name}"
            if t.category:
                return t.category.name
            return "-"

        return {
            "total": total,
            "transactions": [
                {
                    "id": t.id,
                    "account_id": t.account_id,
                    "account_name": t.account.name if t.account else "-",
                    "category_id": t.category_id,
                    "category_name": category_label(t),
                    "payment_method_id": t.payment_method_id,
                    "payment_method_name": t.payment_method.name if t.payment_method else "-",
                    "type": t.transaction_type.value,
                    "amount": float(t.amount),
                    "currency": t.currency,
                    "description": t.description,
                    "merchant": t.merchant,
                    "date": t.date.isoformat(),
                    "is_reconciled": t.is_reconciled,
                }
                for t in transactions
            ],
        }


@router.get("/categories")
async def get_categories() -> list[dict[str, Any]]:
    """Get all categories."""
    with DatabaseSession() as session:
        categories = session.execute(select(Category)).scalars().all()

        tree: dict[int, dict[str, Any]] = {}
        for cat in categories:
            if cat.parent_id is None:
                tree[cat.id] = {"id": cat.id, "name": cat.name, "subcategories": []}

        for cat in categories:
            if cat.parent_id and cat.parent_id in tree:
                tree[cat.parent_id]["subcategories"].append({"id": cat.id, "name": cat.name})

        return list(tree.values())


@router.get("/holdings")
async def get_holdings() -> list[dict[str, Any]]:
    """Get all holdings."""
    with DatabaseSession() as session:
        holdings = session.execute(select(Holding)).scalars().all()

        return [
            {
                "id": h.id,
                "symbol": h.symbol,
                "name": h.name,
                "quantity": float(h.quantity),
                "average_cost": float(h.average_cost),
                "current_price": float(h.current_price) if h.current_price else None,
                "market_value": float(h.quantity * (h.current_price or 0)),
                "last_updated": h.last_updated.isoformat() if h.last_updated else None,
            }
            for h in holdings
        ]


@router.get("/spending-by-category")
async def get_spending_by_category(
    months: int = Query(12),
    transaction_type: str = Query("expense"),
) -> list[dict[str, Any]]:
    """Get spending by category for a given period."""
    with DatabaseSession() as session:
        start_date = datetime.now() - timedelta(days=months * 30)

        query = (
            select(Category.name, func.sum(Transaction.amount).label("total"))
            .join(Transaction, Transaction.category_id == Category.id)
            .filter(Transaction.transaction_type == TransactionType.EXPENSE)
            .filter(Transaction.date >= start_date)
            .group_by(Category.name)
            .order_by(func.sum(Transaction.amount).desc())
        )

        results = session.execute(query).all()

        return [{"category": r.name, "amount": float(r.total)} for r in results]


@router.get("/net-worth-history")
async def get_net_worth_history(
    months: int = Query(4),
) -> list[dict[str, Any]]:
    """Get net worth history (payment methods + investments) for the last N months."""
    with DatabaseSession() as session:
        payment_methods = session.execute(select(PaymentMethod)).scalars().all()
        holdings = session.execute(select(Holding)).scalars().all()

        total_payment = sum(pm.balance for pm in payment_methods)
        total_investments = sum(float(h.quantity * (h.current_price or 0)) for h in holdings)

        history = []
        today = datetime.now()
        for i in range(months):
            month_date = today - timedelta(days=(months - 1 - i) * 30)
            history.append(
                {
                    "date": month_date.strftime("%Y-%m"),
                    "payment_balance": float(total_payment),
                    "investments": total_investments,
                    "net_worth": float(total_payment) + total_investments,
                }
            )

        return history


@router.get("/plots")
async def get_plots() -> list[dict[str, Any]]:
    """Get all persistent plots."""
    with DatabaseSession() as session:
        plots = session.execute(select(DashboardPlot)).scalars().all()

        return [
            {
                "id": p.id,
                "name": p.name,
                "plot_type": p.plot_type,
                "title": p.title,
                "x_key": p.x_key,
                "y_key": p.y_key,
                "config": json.loads(p.config_json) if p.config_json else {},
            }
            for p in plots
        ]


@router.post("/plots")
async def create_plot(config: PlotConfig) -> dict[str, Any]:
    """Create a new persistent plot."""
    with DatabaseSession() as session:
        plot = DashboardPlot(
            name=config.title,
            plot_type=config.plot_type,
            title=config.title,
            x_key=config.x_key,
            y_key=config.y_key,
            config_json=json.dumps(config.config),
        )
        session.add(plot)
        session.commit()
        session.refresh(plot)

        return {
            "id": plot.id,
            "name": plot.name,
            "plot_type": plot.plot_type,
            "title": plot.title,
        }


@router.delete("/plots/{plot_id}")
async def delete_plot(plot_id: int) -> dict[str, str]:
    """Delete a persistent plot."""
    with DatabaseSession() as session:
        plot = session.execute(
            select(DashboardPlot).where(DashboardPlot.id == plot_id)
        ).scalar_one_or_none()

        if not plot:
            raise HTTPException(status_code=404, detail="Plot not found")

        session.delete(plot)
        session.commit()

        return {"status": "deleted"}


@router.get("/monthly-spending")
async def get_monthly_spending(months: int = Query(6)) -> list[dict[str, Any]]:
    """Get monthly spending trend."""
    with DatabaseSession() as session:
        start_date = datetime.now() - timedelta(days=months * 30)

        query = (
            select(
                func.strftime("%Y-%m", Transaction.date).label("month"),
                func.sum(Transaction.amount).label("total"),
            )
            .filter(Transaction.transaction_type == TransactionType.EXPENSE)
            .filter(Transaction.date >= start_date)
            .group_by(func.strftime("%Y-%m", Transaction.date))
            .order_by(func.strftime("%Y-%m", Transaction.date))
        )

        results = session.execute(query).all()

        return [{"month": r.month, "amount": float(r.total)} for r in results]


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get user settings including currency."""
    with DatabaseSession() as session:
        settings_rows = session.execute(select(Settings)).scalars().all()
        data = {s.key: s.value for s in settings_rows}
        return {
            "currency": data.get("currency", "USD"),
        }


@router.get("/audit-log")
async def get_audit_log(limit: int = Query(50, le=200)) -> list[dict[str, Any]]:
    """Get recent audit log entries."""
    with DatabaseSession() as session:
        entries = (
            session.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": e.id,
                "table_name": e.table_name,
                "record_id": e.record_id,
                "operation": e.operation,
                "tool_name": e.tool_name,
                "before_state": json.loads(e.before_state) if e.before_state else None,
                "after_state": json.loads(e.after_state) if e.after_state else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ]


@router.post("/audit-log/{entry_id}/undo")
async def undo_audit_entry(entry_id: int) -> dict[str, Any]:
    """Undo a specific audit log entry by restoring the before state."""
    import json as _json

    with DatabaseSession() as session:
        entry = session.execute(
            select(AuditLog).where(AuditLog.id == entry_id)
        ).scalar_one_or_none()

        if not entry:
            raise HTTPException(status_code=404, detail="Audit entry not found")

        if entry.operation == "create" and entry.after_state:
            after = _json.loads(entry.after_state)
            record_id = after.get("id") or entry.record_id
            if entry.table_name == "transactions" and record_id:
                tx = session.execute(
                    select(Transaction).where(Transaction.id == record_id)
                ).scalar_one_or_none()
                if tx:
                    account = session.execute(
                        select(Account).where(Account.id == tx.account_id)
                    ).scalar_one_or_none()
                    if account:
                        if tx.transaction_type == TransactionType.EXPENSE:
                            account.balance += tx.amount
                        elif tx.transaction_type == TransactionType.INCOME:
                            account.balance -= tx.amount
                    if tx.payment_method:
                        if tx.transaction_type == TransactionType.EXPENSE:
                            tx.payment_method.balance += tx.amount
                        elif tx.transaction_type == TransactionType.INCOME:
                            tx.payment_method.balance -= tx.amount
                    session.delete(tx)
            elif entry.table_name == "payment_methods" and record_id:
                pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.id == record_id)
                ).scalar_one_or_none()
                if pm:
                    session.delete(pm)

        elif entry.operation == "update" and entry.before_state:
            before = _json.loads(entry.before_state)
            record_id = before.get("id") or entry.record_id
            if entry.table_name == "payment_methods" and record_id:
                pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.id == record_id)
                ).scalar_one_or_none()
                if pm and "balance" in before:
                    from decimal import Decimal
                    pm.balance = Decimal(str(before["balance"]))

        session.commit()
        session.delete(entry)
        session.commit()

        return {"status": "undone", "entry_id": entry_id}
