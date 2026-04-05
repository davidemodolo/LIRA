"""initial schema with settings, payment methods, categories

Revision ID: d152c555484c
Revises:
Create Date: 2026-04-05 20:11:30.811481

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d152c555484c"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "account_type",
            sa.Enum(
                "CHECKING",
                "SAVINGS",
                "CREDIT_CARD",
                "INVESTMENT",
                "CASH",
                "LOAN",
                "MORTGAGE",
                "BROKERAGE",
                "RETIREMENT",
                name="accounttype",
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("balance", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("institution", sa.String(length=255), nullable=True),
        sa.Column("account_number", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_accounts_type_active", "accounts", ["account_type", "is_active"], unique=False
    )
    op.create_index("ix_accounts_currency", "accounts", ["currency"], unique=False)
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_categories_name", "categories", ["name"], unique=False)
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("balance", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_payment_methods_name", "payment_methods", ["name"], unique=False)
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("payment_method_id", sa.Integer(), nullable=True),
        sa.Column(
            "transaction_type",
            sa.Enum(
                "INCOME",
                "EXPENSE",
                "TRANSFER",
                "DIVIDEND",
                "BUY",
                "SELL",
                "FEE",
                "INTEREST",
                name="transactiontype",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("is_reconciled", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_methods.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transactions_date_type", "transactions", ["date", "transaction_type"], unique=False
    )
    op.create_index(
        "ix_transactions_account_date", "transactions", ["account_id", "date"], unique=False
    )
    op.create_index("ix_transactions_category", "transactions", ["category_id"], unique=False)
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("average_cost", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_symbol"),
    )
    op.create_index("ix_holdings_symbol", "holdings", ["symbol"], unique=False)
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "trade_type",
            sa.Enum(
                "INCOME",
                "EXPENSE",
                "TRANSFER",
                "DIVIDEND",
                "BUY",
                "SELL",
                "FEE",
                "INTEREST",
                name="transactiontype",
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("fees", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("total", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_symbol_date", "trades", ["symbol", "date"], unique=False)
    op.create_index("ix_trades_portfolio_date", "trades", ["portfolio_id", "date"], unique=False)
    op.create_table(
        "lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("remaining", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("purchase_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lots_holding_date", "lots", ["holding_id", "purchase_date"], unique=False)
    op.create_table(
        "lot_sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("proceeds", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("cost_basis", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("gain_loss", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("sale_date", sa.DateTime(), nullable=False),
        sa.Column("is_short_term", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["lots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lot_sales_sale_date", "lot_sales", ["sale_date"], unique=False)
    op.create_index("ix_lot_sales_gain_loss", "lot_sales", ["gain_loss"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_lot_sales_gain_loss", table_name="lot_sales")
    op.drop_index("ix_lot_sales_sale_date", table_name="lot_sales")
    op.drop_table("lot_sales")
    op.drop_index("ix_lots_holding_date", table_name="lots")
    op.drop_table("lots")
    op.drop_index("ix_trades_portfolio_date", table_name="trades")
    op.drop_index("ix_trades_symbol_date", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_holdings_symbol", table_name="holdings")
    op.drop_table("holdings")
    op.drop_table("portfolios")
    op.drop_index("ix_transactions_category", table_name="transactions")
    op.drop_index("ix_transactions_account_date", table_name="transactions")
    op.drop_index("ix_transactions_date_type", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("settings")
    op.drop_index("ix_payment_methods_name", table_name="payment_methods")
    op.drop_table("payment_methods")
    op.drop_index("ix_categories_name", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_accounts_currency", table_name="accounts")
    op.drop_index("ix_accounts_type_active", table_name="accounts")
    op.drop_table("accounts")
