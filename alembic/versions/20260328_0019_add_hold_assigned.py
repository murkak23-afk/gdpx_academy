"""add hold_assigned column to submissions

Revision ID: 20260328_0019
Revises: 20260328_0018
Create Date: 2026-03-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260328_0019"
down_revision = "20260328_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("hold_assigned", sa.String(length=60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "hold_assigned")
