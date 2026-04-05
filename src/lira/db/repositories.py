"""Repository layer for database operations."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from lira.db.models import (
    Account,
    AccountType,
    Category,
    Portfolio,
    Transaction,
    TransactionType,
)

logger = logging.getLogger(__name__)


class AccountRepository:
    """Repository for Account CRUD operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        account_type: AccountType | str,
        currency: str = "USD",
        balance: Decimal = Decimal("0"),
        institution: str | None = None,
        account_number: str | None = None,
        notes: str | None = None,
    ) -> Account:
        """Create a new account."""
        if isinstance(account_type, str):
            account_type = AccountType(account_type)

        account = Account(
            name=name,
            account_type=account_type,
            currency=currency,
            balance=balance,
            institution=institution,
            account_number=account_number,
            notes=notes,
        )
        self.session.add(account)
        self.session.commit()
        self.session.refresh(account)
        logger.info("Created account: %s (ID: %d)", name, account.id)
        return account

    def get(self, account_id: int) -> Account | None:
        """Get account by ID."""
        return self.session.get(Account, account_id)

    def get_all(self, active_only: bool = True) -> list[Account]:
        """Get all accounts."""
        query = select(Account)
        if active_only:
            query = query.where(Account.is_active == True)
        return list(self.session.execute(query).scalars().all())

    def update(
        self,
        account_id: int,
        name: str | None = None,
        balance: Decimal | None = None,
        institution: str | None = None,
        is_active: bool | None = None,
        notes: str | None = None,
    ) -> Account | None:
        """Update an account."""
        account = self.get(account_id)
        if not account:
            return None

        if name is not None:
            account.name = name
        if balance is not None:
            account.balance = balance
        if institution is not None:
            account.institution = institution
        if is_active is not None:
            account.is_active = is_active
        if notes is not None:
            account.notes = notes

        self.session.commit()
        self.session.refresh(account)
        logger.info("Updated account: %d", account_id)
        return account

    def delete(self, account_id: int) -> bool:
        """Soft delete an account."""
        account = self.get(account_id)
        if not account:
            return False

        account.is_active = False
        self.session.commit()
        logger.info("Deactivated account: %d", account_id)
        return True

    def update_balance(self, account_id: int, amount: Decimal) -> Account | None:
        """Update account balance by adding/subtracting amount."""
        account = self.get(account_id)
        if not account:
            return None

        account.balance += amount
        self.session.commit()
        self.session.refresh(account)
        return account


class TransactionRepository:
    """Repository for Transaction CRUD operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        account_id: int,
        transaction_type: TransactionType | str,
        amount: Decimal,
        currency: str = "USD",
        category_id: int | None = None,
        description: str | None = None,
        merchant: str | None = None,
        date: datetime | None = None,
        notes: str | None = None,
        tags: str | None = None,
    ) -> Transaction:
        """Create a new transaction."""
        if isinstance(transaction_type, str):
            transaction_type = TransactionType(transaction_type)

        transaction = Transaction(
            account_id=account_id,
            category_id=category_id,
            transaction_type=transaction_type,
            amount=amount,
            currency=currency,
            description=description,
            merchant=merchant,
            date=date or datetime.utcnow(),
            notes=notes,
            tags=tags,
        )
        self.session.add(transaction)
        self.session.commit()
        self.session.refresh(transaction)

        account_repo = AccountRepository(self.session)
        account_repo.update_balance(account_id, amount)

        logger.info(
            "Created transaction: %s %s (Account: %d)",
            transaction_type.value,
            amount,
            account_id,
        )
        return transaction

    def get(self, transaction_id: int) -> Transaction | None:
        """Get transaction by ID."""
        return self.session.get(Transaction, transaction_id)

    def get_all(
        self,
        account_id: int | None = None,
        category_id: int | None = None,
        transaction_type: TransactionType | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Transaction]:
        """Get transactions with filters."""
        query = select(Transaction)

        if account_id:
            query = query.where(Transaction.account_id == account_id)
        if category_id:
            query = query.where(Transaction.category_id == category_id)
        if transaction_type:
            query = query.where(Transaction.transaction_type == transaction_type)
        if start_date:
            query = query.where(Transaction.date >= start_date)
        if end_date:
            query = query.where(Transaction.date <= end_date)

        query = query.order_by(Transaction.date.desc()).offset(offset).limit(limit)
        return list(self.session.execute(query).scalars().all())

    def update(
        self,
        transaction_id: int,
        category_id: int | None = None,
        description: str | None = None,
        merchant: str | None = None,
        notes: str | None = None,
        tags: str | None = None,
        is_reconciled: bool | None = None,
    ) -> Transaction | None:
        """Update a transaction."""
        transaction = self.get(transaction_id)
        if not transaction:
            return None

        if category_id is not None:
            transaction.category_id = category_id
        if description is not None:
            transaction.description = description
        if merchant is not None:
            transaction.merchant = merchant
        if notes is not None:
            transaction.notes = notes
        if tags is not None:
            transaction.tags = tags
        if is_reconciled is not None:
            transaction.is_reconciled = is_reconciled

        self.session.commit()
        self.session.refresh(transaction)
        return transaction

    def delete(self, transaction_id: int) -> bool:
        """Delete a transaction and reverse the balance change."""
        transaction = self.get(transaction_id)
        if not transaction:
            return False

        account_id = transaction.account_id
        amount = transaction.amount

        self.session.delete(transaction)
        self.session.commit()

        account_repo = AccountRepository(self.session)
        account_repo.update_balance(account_id, -amount)

        logger.info("Deleted transaction: %d", transaction_id)
        return True


class CategoryRepository:
    """Repository for Category CRUD operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        parent_id: int | None = None,
        icon: str | None = None,
        color: str | None = None,
    ) -> Category:
        """Create a new category."""
        category = Category(
            name=name,
            parent_id=parent_id,
            icon=icon,
            color=color,
        )
        self.session.add(category)
        self.session.commit()
        self.session.refresh(category)
        return category

    def get(self, category_id: int) -> Category | None:
        """Get category by ID."""
        return self.session.get(Category, category_id)

    def get_by_name(self, name: str) -> Category | None:
        """Get category by name."""
        return self.session.execute(
            select(Category).where(Category.name == name)
        ).scalar_one_or_none()

    def get_all(self) -> list[Category]:
        """Get all categories."""
        return list(self.session.execute(select(Category)).scalars().all())


class PortfolioRepository:
    """Repository for Portfolio CRUD operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        description: str | None = None,
        currency: str = "USD",
    ) -> Portfolio:
        """Create a new portfolio."""
        portfolio = Portfolio(
            name=name,
            description=description,
            currency=currency,
        )
        self.session.add(portfolio)
        self.session.commit()
        self.session.refresh(portfolio)
        return portfolio

    def get(self, portfolio_id: int) -> Portfolio | None:
        """Get portfolio by ID."""
        return self.session.get(Portfolio, portfolio_id)

    def get_all(self, active_only: bool = True) -> list[Portfolio]:
        """Get all portfolios."""
        query = select(Portfolio)
        if active_only:
            query = query.where(Portfolio.is_active == True)
        return list(self.session.execute(query).scalars().all())
