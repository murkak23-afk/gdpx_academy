"""add category total upload limit

Revision ID: 20260325_0006
Revises: 20260325_0005
Create Date: 2026-03-25 00:00:06
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260325_0006"
down_revision = "20260325_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("total_upload_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "total_upload_limit")
