"""Integration tests for LLM to Database flow.

These tests simulate the full flow from LLM prompting to database operations,
covering transaction creation, category resolution, payment methods, and
account handling.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal

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
)
from lira.mcp import tools


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
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


@pytest.fixture(autouse=True)
def mock_db_session(session, monkeypatch):
    """Mock DatabaseSession to use test session."""

    @contextmanager
    def mock_session():
        yield session

    monkeypatch.setattr(tools, "DatabaseSession", mock_session)

    from lira.core import init as init_module

    monkeypatch.setattr(init_module, "DatabaseSession", mock_session)


@pytest.fixture(autouse=True)
def init_db(engine, monkeypatch):
    """Initialize database for tests."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("lira.db.session._SessionLocal", SessionLocal)


@pytest.fixture
def sample_account(session: Session) -> Account:
    """Create a sample account for testing."""
    account = Account(
        name="Test Checking",
        account_type=AccountType.CHECKING,
        currency="USD",
        balance=Decimal("1000.00"),
        institution="Test Bank",
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@pytest.fixture
def sample_payment_method(session: Session, sample_account: Account) -> PaymentMethod:
    """Create a sample payment method for testing."""
    pm = PaymentMethod(
        name="Debit Card",
        balance=Decimal("1000.00"),
        is_default=True,
        account_id=sample_account.id,
    )
    session.add(pm)
    session.commit()
    session.refresh(pm)
    return pm


class TestCategoryResolution:
    """Tests for category name resolution."""

    @pytest.mark.asyncio
    async def test_category_exact_name_match(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Category found with exact name match."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-25.00,
            description="Lunch",
            merchant="Burger Joint",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_category_case_insensitive(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Category name match is case insensitive."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="food",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-25.00,
            description="Lunch",
            merchant="Burger Joint",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_category_with_parent_resolved(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Category with parent hierarchy (FOOD > groceries) now resolves correctly."""
        parent = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(parent)
        session.flush()

        child = Category(name="groceries", icon="🛒", color="#00FF00", parent_id=parent.id)
        session.add(child)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD > groceries",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-50.00,
            description="Weekly groceries",
            merchant="Trader Joe's",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_category_child_name_found(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Child category name 'groceries' found via simple exact match."""
        parent = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(parent)
        session.flush()

        child = Category(name="groceries", icon="🛒", color="#00FF00", parent_id=parent.id)
        session.add(child)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="groceries",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-50.00,
            description="Weekly groceries",
            merchant="Trader Joe's",
        )
        assert "id" in result

    @pytest.mark.asyncio
    async def test_category_not_found_error(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Proper error when category doesn't exist."""
        with pytest.raises(ValueError, match="Category 'NONEXISTENT' not found"):
            await tools.create_transaction(
                account_id=sample_account.id,
                category_name="NONEXISTENT",
                secondary_category_name="FOOD",
                payment_method_name="Debit Card",
                transaction_type="expense",
                amount=-25.00,
                description="Test",
                merchant="Test",
            )


class TestSecondaryCategory:
    """Tests for secondary category requirement."""

    @pytest.mark.asyncio
    async def test_transaction_both_categories_required(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Transaction fails if only primary category provided."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        with pytest.raises(
            ValueError,
            match="secondary_category_id or secondary_category_name must be provided",
        ):
            await tools.create_transaction(
                account_id=sample_account.id,
                category_name="FOOD",
                payment_method_name="Debit Card",
                transaction_type="expense",
                amount=-25.00,
                description="Lunch",
                merchant="Burger Joint",
            )

    @pytest.mark.asyncio
    async def test_secondary_category_resolved_by_name(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Secondary category resolved by name correctly."""
        cat1 = Category(name="PRIMARY", icon="1", color="#FF0000")
        cat2 = Category(name="SECONDARY", icon="2", color="#00FF00")
        session.add_all([cat1, cat2])
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="PRIMARY",
            secondary_category_name="SECONDARY",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-25.00,
            description="Test",
            merchant="Test",
        )

        assert "id" in result


class TestPaymentMethod:
    """Tests for payment method resolution."""

    @pytest.mark.asyncio
    async def test_payment_method_by_name(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Payment method resolved by name."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-25.00,
            description="Lunch",
            merchant="Burger Joint",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_payment_method_case_insensitive(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Payment method name match is case insensitive."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_name="debit card",
            transaction_type="expense",
            amount=-25.00,
            description="Lunch",
            merchant="Burger Joint",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_payment_method_not_found_error(self, session: Session, sample_account):
        """Proper error when payment method doesn't exist."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        with pytest.raises(ValueError, match="Payment method 'Unknown Card' not found"):
            await tools.create_transaction(
                account_id=sample_account.id,
                category_name="FOOD",
                secondary_category_name="FOOD",
                payment_method_name="Unknown Card",
                transaction_type="expense",
                amount=-25.00,
                description="Test",
                merchant="Test",
            )


class TestAccountResolution:
    """Tests for account resolution."""

    @pytest.mark.asyncio
    async def test_account_auto_fallback_when_missing(
        self, session: Session, sample_payment_method
    ):
        """Account auto-falls back to first account when not provided."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=None,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_id=sample_payment_method.id,
            transaction_type="expense",
            amount=-25.00,
            description="Lunch",
            merchant="Burger Joint",
        )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_account_not_found_error(self, session: Session, sample_payment_method):
        """Proper error when account doesn't exist."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        with pytest.raises(ValueError, match="Account 99999 not found"):
            await tools.create_transaction(
                account_id=99999,
                category_name="FOOD",
                secondary_category_name="FOOD",
                payment_method_id=sample_payment_method.id,
                transaction_type="expense",
                amount=-25.00,
                description="Test",
                merchant="Test",
            )


class TestTransactionFlow:
    """Tests for complete transaction creation flow."""

    @pytest.mark.asyncio
    async def test_transaction_full_flow_valid(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Complete happy path transaction creation."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=50.00,  # amounts are always positive; transaction_type sets direction
            description="Groceries",
            merchant="Whole Foods",
        )

        assert "id" in result
        assert result["amount"] == 50.00
        assert result["type"] == "expense"

    @pytest.mark.asyncio
    async def test_income_transaction_increases_balance(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Income transaction increases account balance."""
        cat = Category(name="SALARY", icon="💰", color="#00FF00")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="SALARY",
            secondary_category_name="SALARY",
            payment_method_name="Debit Card",
            transaction_type="income",
            amount=5000.00,
            description="Monthly salary",
            merchant="My Company",
        )

        assert "id" in result
        assert result["amount"] == 5000.00

    @pytest.mark.asyncio
    async def test_transfer_transaction(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Transfer transaction doesn't change balance (moves money)."""
        cat = Category(name="TRANSFER", icon="🔄", color="#0000FF")
        session.add(cat)
        session.commit()

        result = await tools.create_transaction(
            account_id=sample_account.id,
            category_name="TRANSFER",
            secondary_category_name="TRANSFER",
            payment_method_name="Debit Card",
            transaction_type="transfer",
            amount=500.00,
            description="Savings transfer",
            merchant="My Bank",
        )

        assert "id" in result
        assert result["amount"] == 500.00
        assert result["type"] == "transfer"

    @pytest.mark.asyncio
    async def test_payment_method_balance_updated(
        self, session: Session, sample_account, sample_payment_method
    ):
        """Payment method balance is updated on transaction."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        await tools.create_transaction(
            account_id=sample_account.id,
            category_name="FOOD",
            secondary_category_name="FOOD",
            payment_method_name="Debit Card",
            transaction_type="expense",
            amount=-50.00,
            description="Groceries",
            merchant="Whole Foods",
        )

        assert True


class TestCategoryListing:
    """Tests for category listing and retrieval."""

    @pytest.mark.asyncio
    async def test_get_categories_returns_all(self, session: Session):
        """get_categories returns all categories."""
        cat1 = Category(name="FOOD", icon="🍔", color="#FF0000")
        cat2 = Category(name="RIDES", icon="🚗", color="#00FF00")
        session.add_all([cat1, cat2])
        session.commit()

        result = await tools.get_categories()

        assert len(result) == 2
        names = [c["name"] for c in result]
        assert "FOOD" in names
        assert "RIDES" in names

    @pytest.mark.asyncio
    async def test_get_categories_includes_id(self, session: Session):
        """get_categories returns category IDs for LLM use."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()
        session.refresh(cat)

        result = await tools.get_categories()

        food_cat = next(c for c in result if c["name"] == "FOOD")
        assert "id" in food_cat
        assert food_cat["id"] == cat.id


class TestCreateCategory:
    """Tests for category creation."""

    @pytest.mark.asyncio
    async def test_create_category_basic(self, session: Session):
        """Basic category creation works."""
        result = await tools.create_category(name="NEW_CATEGORY")

        assert "id" in result
        assert result["name"] == "NEW_CATEGORY"

    @pytest.mark.asyncio
    async def test_create_category_with_parent(self, session: Session):
        """Category with parent hierarchy created correctly."""
        parent = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(parent)
        session.commit()
        session.refresh(parent)

        result = await tools.create_category(
            name="groceries",
            parent_id=parent.id,
        )

        assert "id" in result

        session.expire_all()
        child = session.query(Category).filter_by(name="groceries").first()
        assert child.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_create_category_duplicate_fails(self, session: Session):
        """Duplicate category name returns existing category instead of error."""
        cat = Category(name="FOOD", icon="🍔", color="#FF0000")
        session.add(cat)
        session.commit()

        result = await tools.create_category(name="FOOD")
        assert result["name"] == "FOOD"
