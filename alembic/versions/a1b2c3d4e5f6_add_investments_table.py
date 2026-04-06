"""Add investments table

Revision ID: a1b2c3d4e5f6
Revises: 2f98b9a16ade
Create Date: 2026-04-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "2f98b9a16ade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add investments table for individual trade records."""
    op.create_table(
        "investments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("units", sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column("price_per_unit", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("fees", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "trade_type",
            sa.Enum("buy", "sell", name="investmenttradetype"),
            nullable=False,
        ),
        sa.Column("payment_method_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("broker", sa.String(length=255), nullable=True),
        sa.Column("exchange", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_investments_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_methods.id"],
            name="fk_investments_payment_method_id_payment_methods",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investments_date", "investments", ["date"], unique=False)
    op.create_index(
        "ix_investments_ticker_date", "investments", ["ticker", "date"], unique=False
    )


def downgrade() -> None:
    """Drop investments table."""
    op.drop_index("ix_investments_ticker_date", table_name="investments")
    op.drop_index("ix_investments_date", table_name="investments")
    op.drop_table("investments")
    # Drop the enum type (only needed for non-SQLite databases)
    # op.execute("DROP TYPE IF EXISTS investmenttradetype")
