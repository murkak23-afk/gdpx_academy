"""add locked_by_admin_id

Revision ID: e9fa0e8006a2
Revises: 20260326_0016
Create Date: 2026-03-27 03:39:31.117623
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'e9fa0e8006a2'
down_revision = '20260326_0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("locked_by_admin_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_submissions_locked_by_admin_id",
        "submissions",
        ["locked_by_admin_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_submissions_locked_by_admin_id_users",
        "submissions",
        "users",
        ["locked_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_submissions_locked_by_admin_id_users", "submissions", type_="foreignkey")
    op.drop_index("ix_submissions_locked_by_admin_id", table_name="submissions")
    op.drop_column("submissions", "locked_by_admin_id")
