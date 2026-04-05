"""Test configuration and fixtures for L.I.R.A."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lira.db.models import (
    Account,
    AccountType,
    Base,
    Category,
    PaymentMethod,
    Holding,
    Portfolio,
    Transaction,
    TransactionType,
)


@pytest.fixture(scope="function")
def engine():
    """Create in-memory SQLite engine for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def session(engine) -> Generator[Session, None, None]:
    """Create a new database session for each test."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_account(session: Session) -> Account:
    """Create a sample account for testing."""
    account = Account(
        name="Test Checking Account",
        account_type=AccountType.CHECKING,
        currency="USD",
        balance=Decimal("1000.00"),
        institution="Test Bank",
    )
    session.add(account)
    session.commit()
    return account


@pytest.fixture
def sample_category(session: Session) -> Category:
    """Create a sample category for testing."""
    category = Category(
        name="Groceries",
        icon="🛒",
        color="#4CAF50",
    )
    session.add(category)
    session.commit()
    return category

@pytest.fixture
def sample_payment_method(session: Session, sample_account: Account) -> PaymentMethod:
    pm = PaymentMethod(
        name="Debit Card",
        balance=Decimal("1000.00"),
        is_default=True,
        account_id=sample_account.id,
    )
    session.add(pm)
    session.commit()
    return pm



@pytest.fixture
def sample_transaction(
    session: Session,
    sample_account: Account,
    sample_category: Category,
    sample_payment_method: PaymentMethod,
) -> Transaction:
    """Create a sample transaction for testing."""
    transaction = Transaction(
        account_id=sample_account.id,
        category_id=sample_category.id,
        secondary_category_id=sample_category.id,
        payment_method_id=sample_payment_method.id,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("-50.00"),
        currency="USD",
        description="Weekly groceries",
        merchant="Super Mart",
        date=datetime.utcnow(),
    )
    session.add(transaction)
    session.commit()
    return transaction


@pytest.fixture
def sample_portfolio(session: Session) -> Portfolio:
    """Create a sample portfolio for testing."""
    portfolio = Portfolio(
        name="Test Portfolio",
        description="A portfolio for testing",
        currency="USD",
    )
    session.add(portfolio)
    session.commit()
    return portfolio


@pytest.fixture
def sample_holding(session: Session, sample_portfolio: Portfolio) -> Holding:
    """Create a sample holding for testing."""
    holding = Holding(
        portfolio_id=sample_portfolio.id,
        symbol="AAPL",
        name="Apple Inc.",
        quantity=Decimal("10.0000"),
        average_cost=Decimal("150.00"),
        current_price=Decimal("175.00"),
        last_updated=datetime.utcnow(),
    )
    session.add(holding)
    session.commit()
    return holding


@pytest.fixture
def multiple_transactions(
    session: Session,
    sample_account: Account,
    sample_category: Category,
    sample_payment_method: PaymentMethod,
) -> list[Transaction]:
    """Create multiple transactions for testing."""
    transactions = [
        Transaction(
            account_id=sample_account.id,
            category_id=sample_category.id,
            secondary_category_id=sample_category.id,
            payment_method_id=sample_payment_method.id,
            transaction_type=TransactionType.INCOME,
            amount=Decimal("5000.00"),
            currency="USD",
            description="Salary",
            merchant="My Company",
            date=datetime(2024, 1, 15),
        ),
        Transaction(
            account_id=sample_account.id,
            category_id=sample_category.id,
            secondary_category_id=sample_category.id,
            payment_method_id=sample_payment_method.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("-100.00"),
            currency="USD",
            description="Groceries",
            merchant="Super Mart",
            date=datetime(2024, 1, 16),
        ),
        Transaction(
            account_id=sample_account.id,
            category_id=sample_category.id,
            secondary_category_id=sample_category.id,
            payment_method_id=sample_payment_method.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("-50.00"),
            currency="USD",
            description="Gas",
            merchant="Gas Station",
            date=datetime(2024, 1, 17),
        ),
        Transaction(
            account_id=sample_account.id,
            category_id=sample_category.id,
            secondary_category_id=sample_category.id,
            payment_method_id=sample_payment_method.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("-200.00"),
            currency="USD",
            description="Rent",
            merchant="Landlord",
            date=datetime(2024, 1, 1),
        ),
        Transaction(
            account_id=sample_account.id,
            category_id=sample_category.id,
            secondary_category_id=sample_category.id,
            payment_method_id=sample_payment_method.id,
            transaction_type=TransactionType.TRANSFER,
            amount=Decimal("500.00"),
            currency="USD",
            description="Savings transfer",
            merchant="My Bank",
            date=datetime(2024, 1, 20),
        ),
    ]

    for t in transactions:
        session.add(t)
    session.commit()
    return transactions


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider for testing."""
    provider = MagicMock()
    provider.complete.return_value = "Mocked response"
    provider.acomplete.return_value = "Mocked async response"
    return provider


@pytest.fixture
def sample_account_data() -> dict:
    """Sample account data for testing."""
    return {
        "name": "Savings Account",
        "account_type": AccountType.SAVINGS,
        "currency": "USD",
        "balance": Decimal("5000.00"),
        "institution": "Test Savings Bank",
    }


@pytest.fixture
def sample_transaction_data() -> dict:
    """Sample transaction data for testing."""
    return {
        "transaction_type": TransactionType.EXPENSE,
        "amount": Decimal("-75.50"),
        "currency": "USD",
        "description": "Restaurant dinner",
        "merchant": "Italian Kitchen",
    }
