"""drop locked_by_admin_id column

Revision ID: 20260401_0022
Revises: 20260329_0021
Create Date: 2026-04-01 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260401_0022"
down_revision = "20260329_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_submissions_locked_by_admin_id_users", "submissions", type_="foreignkey")
    op.drop_index("ix_submissions_locked_by_admin_id", table_name="submissions")
    op.drop_column("submissions", "locked_by_admin_id")


def downgrade() -> None:
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
