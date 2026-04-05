"""Analytics service for financial analysis.

Provides analytical capabilities for:
- Spending analysis
- Trend detection
- Budget tracking
- Forecasting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from lira.db.models import Category, Transaction, TransactionType

logger = logging.getLogger(__name__)


@dataclass
class SpendingByCategory:
    """Spending breakdown by category."""

    category: str
    total: Decimal
    count: int
    percentage: Decimal


@dataclass
class SpendingTrend:
    """Spending trend data."""

    period: str
    total: Decimal
    change: Decimal
    change_percent: Decimal


@dataclass
class MonthlySummary:
    """Monthly spending summary."""

    month: str
    income: Decimal
    expenses: Decimal
    net: Decimal
    by_category: list[SpendingByCategory]


class AnalyticsService:
    """Service for financial analytics."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_spending_by_category(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        account_id: int | None = None,
    ) -> list[SpendingByCategory]:
        """Get spending breakdown by category.

        Args:
            start_date: Start date filter
            end_date: End date filter
            account_id: Account filter

        Returns:
            List of spending by category
        """
        query = (
            self.session.query(
                Category.name,
                Transaction.amount,
            )
            .join(Transaction)
            .filter(Transaction.transaction_type == TransactionType.EXPENSE)
        )

        if start_date:
            query = query.filter(Transaction.date >= start_date)
        if end_date:
            query = query.filter(Transaction.date <= end_date)
        if account_id:
            query = query.filter(Transaction.account_id == account_id)

        results = query.all()

        by_category: dict[str, dict[str, Any]] = {}
        for name, amount in results:
            if name not in by_category:
                by_category[name] = {"total": Decimal("0"), "count": 0}
            by_category[name]["total"] += abs(amount)
            by_category[name]["count"] += 1

        total_spending = sum(c["total"] for c in by_category.values())

        spending_list = [
            SpendingByCategory(
                category=name,
                total=data["total"],
                count=data["count"],
                percentage=(
                    (data["total"] / total_spending * 100) if total_spending else Decimal("0")
                ),
            )
            for name, data in by_category.items()
        ]

        return sorted(spending_list, key=lambda x: x.total, reverse=True)

    def get_monthly_summary(
        self,
        year: int,
        month: int | None = None,
    ) -> list[MonthlySummary]:
        """Get monthly spending summaries.

        Args:
            year: Year
            month: Optional specific month

        Returns:
            List of monthly summaries
        """
        start = datetime(year, 1, 1)
        if month:
            start = datetime(year, month, 1)
            if month == 12:
                end = datetime(year + 1, 1, 1)
            else:
                end = datetime(year, month + 1, 1)
        else:
            end = datetime(year + 1, 1, 1)

        transactions = (
            self.session.query(Transaction)
            .filter(
                Transaction.date >= start,
                Transaction.date < end,
            )
            .all()
        )

        monthly_data: dict[str, dict[str, Any]] = {}

        for t in transactions:
            month_key = t.date.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    "income": Decimal("0"),
                    "expenses": Decimal("0"),
                    "by_category": {},
                }

            amount = t.amount
            if t.transaction_type == TransactionType.INCOME:
                monthly_data[month_key]["income"] += amount
            elif t.transaction_type == TransactionType.EXPENSE:
                monthly_data[month_key]["expenses"] += abs(amount)
                cat_name = t.category.name if t.category else "Uncategorized"
                if cat_name not in monthly_data[month_key]["by_category"]:
                    monthly_data[month_key]["by_category"][cat_name] = Decimal("0")
                monthly_data[month_key]["by_category"][cat_name] += abs(amount)

        summaries = []
        for month_key, data in sorted(monthly_data.items()):
            total_spending = sum(data["by_category"].values())
            by_category = [
                SpendingByCategory(
                    category=cat,
                    total=total,
                    count=0,
                    percentage=((total / total_spending * 100) if total_spending else Decimal("0")),
                )
                for cat, total in data["by_category"].items()
            ]

            summaries.append(
                MonthlySummary(
                    month=month_key,
                    income=data["income"],
                    expenses=data["expenses"],
                    net=data["income"] - data["expenses"],
                    by_category=sorted(by_category, key=lambda x: x.total, reverse=True),
                )
            )

        return summaries

    def get_spending_trend(
        self,
        days: int = 30,
        granularity: str = "day",
    ) -> list[SpendingTrend]:
        """Get spending trend over time.

        Args:
            days: Number of days to analyze
            granularity: Trend granularity (day, week, month)

        Returns:
            List of spending trends
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        transactions = (
            self.session.query(Transaction)
            .filter(
                Transaction.date >= start_date,
                Transaction.transaction_type == TransactionType.EXPENSE,
            )
            .all()
        )

        if granularity == "day":
            period_format = "%Y-%m-%d"
            delta = timedelta(days=1)
        elif granularity == "week":
            period_format = "%Y-W%W"
            delta = timedelta(weeks=1)
        else:
            period_format = "%Y-%m"
            delta = timedelta(days=30)

        by_period: dict[str, Decimal] = {}
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        while current < end_date:
            period_key = current.strftime(period_format)
            by_period[period_key] = Decimal("0")
            current += delta

        for t in transactions:
            period_key = t.date.strftime(period_format)
            if period_key in by_period:
                by_period[period_key] += abs(t.amount)

        trends = []
        sorted_periods = sorted(by_period.keys())
        prev_total = Decimal("0")

        for period in sorted_periods:
            total = by_period[period]
            change = total - prev_total
            change_pct = (change / prev_total * 100) if prev_total else Decimal("0")

            trends.append(
                SpendingTrend(
                    period=period,
                    total=total,
                    change=change,
                    change_percent=change_pct,
                )
            )

            prev_total = total

        return trends

    def detect_anomalies(
        self,
        days: int = 30,
        threshold: Decimal = Decimal("2"),
    ) -> list[dict[str, Any]]:
        """Detect spending anomalies using statistical methods.

        Args:
            days: Days to analyze
            threshold: Standard deviations for anomaly detection

        Returns:
            List of detected anomalies
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        transactions = (
            self.session.query(Transaction)
            .filter(
                Transaction.date >= start_date,
                Transaction.transaction_type == TransactionType.EXPENSE,
            )
            .all()
        )

        if len(transactions) < 5:
            return []

        amounts = [abs(t.amount) for t in transactions]
        mean = sum(amounts) / len(amounts)

        variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
        std_dev = Decimal(str(variance**0.5))

        anomalies = []
        for t in transactions:
            amount = abs(t.amount)
            z_score = (amount - mean) / std_dev if std_dev else Decimal("0")

            if z_score > threshold:
                anomalies.append(
                    {
                        "transaction_id": t.id,
                        "date": t.date.isoformat(),
                        "amount": float(amount),
                        "description": t.description,
                        "merchant": t.merchant,
                        "category": t.category.name if t.category else None,
                        "z_score": float(z_score),
                    }
                )

        return anomalies
