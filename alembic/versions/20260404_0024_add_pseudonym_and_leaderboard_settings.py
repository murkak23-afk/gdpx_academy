"""add pseudonym to users and leaderboard_settings table

Revision ID: 20260404_0024
Revises: 20260403_0001
Create Date: 2026-04-04 00:00:01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260404_0024"
down_revision = "20260403_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users.pseudonym ─────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "pseudonym",
            sa.String(32),
            nullable=True,
            comment="Public alias used on the leaderboard. NULL = onboarding not completed.",
        ),
    )
    op.create_index("ix_users_pseudonym", "users", ["pseudonym"], unique=True)

    # ── leaderboard_settings ─────────────────────────────────────────
    op.create_table(
        "leaderboard_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "prize_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("prize_text", sa.String(512), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    # Ensure exactly one settings row always exists.
    op.execute("INSERT INTO leaderboard_settings (prize_enabled) VALUES (false)")


def downgrade() -> None:
    op.drop_table("leaderboard_settings")
    op.drop_index("ix_users_pseudonym", table_name="users")
    op.drop_column("users", "pseudonym")
