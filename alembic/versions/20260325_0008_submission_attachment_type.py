"""submission attachment_type photo or document

Revision ID: 20260325_0008
Revises: 20260325_0007
Create Date: 2026-03-25 00:00:08
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260325_0008"
down_revision = "20260325_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("attachment_type", sa.String(length=16), nullable=False, server_default="photo"),
    )
    op.create_index("ix_submissions_attachment_type", "submissions", ["attachment_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_submissions_attachment_type", table_name="submissions")
    op.drop_column("submissions", "attachment_type")
