"""add defaults for timestamp columns

Revision ID: 20260325_0004
Revises: 20260325_0003
Create Date: 2026-03-25 00:00:04
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260325_0004"
down_revision = "20260325_0003"
branch_labels = None
depends_on = None


def _set_defaults(table_name: str) -> None:
    op.alter_column(
        table_name,
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=False,
    )
    op.alter_column(
        table_name,
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=False,
    )


def _drop_defaults(table_name: str) -> None:
    op.alter_column(
        table_name,
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        table_name,
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        existing_nullable=False,
    )


def upgrade() -> None:
    for table_name in [
        "users",
        "categories",
        "submissions",
        "review_actions",
        "publication_archives",
        "payouts",
    ]:
        _set_defaults(table_name)


def downgrade() -> None:
    for table_name in [
        "payouts",
        "publication_archives",
        "review_actions",
        "submissions",
        "categories",
        "users",
    ]:
        _drop_defaults(table_name)
