"""Unit tests for Account model."""

from decimal import Decimal

from lira.db.models import Account, AccountType


def test_account_creation(session, sample_account_data):
    """Test creating a new account."""
    account = Account(**sample_account_data)
    session.add(account)
    session.commit()

    assert account.id is not None
    assert account.name == "Savings Account"
    assert account.account_type == AccountType.SAVINGS
    assert account.balance == Decimal("5000.00")
    assert account.is_active is True


def test_account_update_balance(session, sample_account):
    """Test updating account balance."""
    initial_balance = sample_account.balance
    new_balance = Decimal("1500.00")

    sample_account.balance = new_balance
    session.commit()

    refreshed = session.query(Account).filter_by(id=sample_account.id).first()
    assert refreshed.balance == new_balance
    assert refreshed.balance != initial_balance


def test_account_deactivation(session, sample_account):
    """Test deactivating an account."""
    assert sample_account.is_active is True

    sample_account.is_active = False
    session.commit()

    refreshed = session.query(Account).filter_by(id=sample_account.id).first()
    assert refreshed.is_active is False


def test_account_multiple_types(session):
    """Test creating accounts of different types."""
    accounts = [
        Account(name="Checking", account_type=AccountType.CHECKING, balance=Decimal("1000")),
        Account(name="Savings", account_type=AccountType.SAVINGS, balance=Decimal("5000")),
        Account(name="Credit Card", account_type=AccountType.CREDIT_CARD, balance=Decimal("-500")),
        Account(name="Investment", account_type=AccountType.INVESTMENT, balance=Decimal("10000")),
    ]

    for acc in accounts:
        session.add(acc)
    session.commit()

    all_accounts = session.query(Account).all()
    assert len(all_accounts) == 4

    types = [acc.account_type for acc in all_accounts]
    assert AccountType.CHECKING in types
    assert AccountType.SAVINGS in types
    assert AccountType.CREDIT_CARD in types
    assert AccountType.INVESTMENT in types
