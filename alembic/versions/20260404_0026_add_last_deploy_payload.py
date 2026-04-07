"""Add last_deploy_payload column to users table.

Revision ID: 20260404_0026
Revises: 20260404_0025
Create Date: 2026-04-04 00:00:03

Purpose
───────
Stores the last successful eSIM upload context per seller so the
One-Tap Deploy (⚡ ПОВТОРИТЬ) button can bypass the category-selection
step in the upload FSM.

Payload shape: {"category_id": int, "label": str}
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260404_0026"
down_revision = "20260404_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_deploy_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_deploy_payload")
