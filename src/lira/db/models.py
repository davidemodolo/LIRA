"""SQLAlchemy models for L.I.R.A.

This module defines the core database models for financial tracking.
All models use SQLAlchemy 2.0 style with type annotations.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    type_annotation_map = {
        Decimal: Numeric(precision=19, scale=4),
    }


class TransactionType(str, enum.Enum):
    """Types of financial transactions."""

    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    DIVIDEND = "dividend"
    BUY = "buy"
    SELL = "sell"
    FEE = "fee"
    INTEREST = "interest"


class AccountType(str, enum.Enum):
    """Types of accounts."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    CASH = "cash"
    LOAN = "loan"
    MORTGAGE = "mortgage"
    BROKERAGE = "brokerage"
    RETIREMENT = "retirement"


class Account(Base):
    """Financial account model.

    Represents a bank account, credit card, investment account, etc.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_accounts_type_active", "account_type", "is_active"),
        Index("ix_accounts_currency", "currency"),
    )


class Category(Base):
    """Transaction category model.

    Categories are used to classify transactions for analysis.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    parent: Mapped[Category | None] = relationship(
        "Category", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[Category]] = relationship("Category", back_populates="parent")
    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="category")

    __table_args__ = (Index("ix_categories_name", "name"),)


class Transaction(Base):
    """Financial transaction model.

    Represents a single financial transaction (income, expense, transfer, etc.).
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account: Mapped[Account] = relationship("Account", back_populates="transactions")
    category: Mapped[Category | None] = relationship("Category", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_date_type", "date", "transaction_type"),
        Index("ix_transactions_account_date", "account_id", "date"),
        Index("ix_transactions_category", "category_id"),
    )


class Portfolio(Base):
    """Investment portfolio model.

    Represents a collection of holdings in various securities.
    """

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    holdings: Mapped[list[Holding]] = relationship(
        "Holding",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    trades: Mapped[list[Trade]] = relationship(
        "Trade",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )


class Holding(Base):
    """Current holding in a security.

    Represents the current position in a stock, bond, ETF, etc.
    """

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolios.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    portfolio: Mapped[Portfolio] = relationship("Portfolio", back_populates="holdings")
    lots: Mapped[list[Lot]] = relationship(
        "Lot", back_populates="holding", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_symbol"),
    )


class Trade(Base):
    """Trade execution record.

    Records individual buy/sell transactions for tax lot tracking.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolios.id"), nullable=False)
    holding_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("holdings.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    portfolio: Mapped[Portfolio] = relationship("Portfolio", back_populates="trades")
    holding: Mapped[Holding | None] = relationship("Holding", back_populates="trades")
    lot: Mapped[Lot | None] = relationship("Lot", back_populates="trade")

    __table_args__ = (
        Index("ix_trades_symbol_date", "symbol", "date"),
        Index("ix_trades_portfolio_date", "portfolio_id", "date"),
    )


class Lot(Base):
    """Tax lot for cost basis tracking.

    Tracks individual purchase lots for FIFO/LIFO tax calculations.
    """

    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holding_id: Mapped[int] = mapped_column(Integer, ForeignKey("holdings.id"), nullable=False)
    trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("trades.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), nullable=False)
    remaining: Mapped[Decimal] = mapped_column(Numeric(19, 8), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    purchase_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    holding: Mapped[Holding] = relationship("Holding", back_populates="lots")
    trade: Mapped[Trade] = relationship("Trade", back_populates="lot")
    sales: Mapped[list[LotSale]] = relationship(
        "LotSale", back_populates="lot", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_lots_holding_date", "holding_id", "purchase_date"),)


class LotSale(Base):
    """Record of shares sold from a specific lot.

    Links lots to sales for tax reporting.
    """

    __tablename__ = "lot_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(Integer, ForeignKey("lots.id"), nullable=False)
    trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("trades.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), nullable=False)
    proceeds: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    gain_loss: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    sale_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_short_term: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lot: Mapped[Lot] = relationship("Lot", back_populates="sales")
    trade: Mapped[Trade] = relationship("Trade")

    __table_args__ = (
        Index("ix_lot_sales_sale_date", "sale_date"),
        Index("ix_lot_sales_gain_loss", "gain_loss"),
    )


# Pydantic schemas for API serialization
class AccountSchema(BaseModel):
    """Pydantic schema for Account."""

    id: int
    name: str
    account_type: AccountType
    currency: str
    balance: Decimal
    institution: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TransactionSchema(BaseModel):
    """Pydantic schema for Transaction."""

    id: int
    account_id: int
    category_id: int | None = None
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    description: str | None = None
    merchant: str | None = None
    date: datetime
    is_reconciled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class HoldingSchema(BaseModel):
    """Pydantic schema for Holding."""

    id: int
    symbol: str
    name: str | None = None
    quantity: Decimal
    average_cost: Decimal
    current_price: Decimal | None = None
    last_updated: datetime | None = None

    model_config = {"from_attributes": True}
