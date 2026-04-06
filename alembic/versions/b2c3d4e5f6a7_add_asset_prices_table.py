"""Add asset_prices table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add asset_prices table for current market prices per ticker."""
    op.create_table(
        "asset_prices",
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )


def downgrade() -> None:
    """Drop asset_prices table."""
    op.drop_table("asset_prices")
