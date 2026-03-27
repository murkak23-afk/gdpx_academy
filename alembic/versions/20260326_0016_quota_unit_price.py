"""Add unit price to seller daily quotas.

Revision ID: 20260326_0016
Revises: 20260326_0015
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260326_0016"
down_revision = "20260326_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seller_daily_quotas",
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.alter_column("seller_daily_quotas", "unit_price", server_default=None)


def downgrade() -> None:
    op.drop_column("seller_daily_quotas", "unit_price")
