"""Unit tests for Transaction model."""

from datetime import datetime
from decimal import Decimal

from lira.db.models import Transaction, TransactionType


def test_transaction_creation(session, sample_account, sample_category):
    """Test creating a new transaction."""
    transaction = Transaction(
        account_id=sample_account.id,
        category_id=sample_category.id,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("-50.00"),
        currency="USD",
        description="Test expense",
        merchant="Test Store",
        date=datetime.utcnow(),
    )
    session.add(transaction)
    session.commit()

    assert transaction.id is not None
    assert transaction.transaction_type == TransactionType.EXPENSE
    assert transaction.amount == Decimal("-50.00")
    assert transaction.is_reconciled is False


def test_transaction_relationships(session, sample_transaction, sample_account, sample_category):
    """Test transaction relationships."""
    assert sample_transaction.account.id == sample_account.id
    assert sample_transaction.category.id == sample_category.id


def test_transaction_query_by_type(session, multiple_transactions):
    """Test querying transactions by type."""
    income_transactions = (
        session.query(Transaction)
        .filter(Transaction.transaction_type == TransactionType.INCOME)
        .all()
    )

    assert len(income_transactions) == 1
    assert income_transactions[0].amount > 0


def test_transaction_query_by_date_range(session, multiple_transactions):
    """Test querying transactions by date range."""
    start = datetime(2024, 1, 10)
    end = datetime(2024, 1, 18)

    filtered = (
        session.query(Transaction)
        .filter(
            Transaction.date >= start,
            Transaction.date <= end,
        )
        .all()
    )

    assert len(filtered) == 3


def test_transaction_total_calculation(session, multiple_transactions):
    """Test calculating total from transactions."""
    total = sum(t.amount for t in multiple_transactions)
    assert total == Decimal("5650.00")
