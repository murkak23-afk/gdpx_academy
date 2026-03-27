"""Add manual finalization fields for submissions.

Revision ID: 20260326_0015
Revises: 20260326_0014
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260326_0015"
down_revision = "20260326_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("submissions", sa.Column("finalized_by_admin_id", sa.Integer(), nullable=True))
    op.add_column("submissions", sa.Column("final_reason", sa.String(length=255), nullable=True))

    op.create_index("ix_submissions_finalized_at", "submissions", ["finalized_at"], unique=False)
    op.create_index("ix_submissions_finalized_by_admin_id", "submissions", ["finalized_by_admin_id"], unique=False)
    op.create_index("ix_submissions_status_created_at", "submissions", ["status", "created_at"], unique=False)
    op.create_index(
        "ix_submissions_admin_status",
        "submissions",
        ["admin_id", "status"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_submissions_finalized_by_admin_id_users",
        "submissions",
        "users",
        ["finalized_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_submissions_finalized_by_admin_id_users", "submissions", type_="foreignkey")
    op.drop_index("ix_submissions_admin_status", table_name="submissions")
    op.drop_index("ix_submissions_status_created_at", table_name="submissions")
    op.drop_index("ix_submissions_finalized_by_admin_id", table_name="submissions")
    op.drop_index("ix_submissions_finalized_at", table_name="submissions")

    op.drop_column("submissions", "final_reason")
    op.drop_column("submissions", "finalized_by_admin_id")
    op.drop_column("submissions", "finalized_at")
