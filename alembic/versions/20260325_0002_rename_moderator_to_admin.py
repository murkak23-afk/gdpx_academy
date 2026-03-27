"""rename moderator columns to admin

Revision ID: 20260325_0002
Revises: 20260325_0001
Create Date: 2026-03-25 00:00:02
"""
from __future__ import annotations

from alembic import op

revision = "20260325_0002"
down_revision = "20260325_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("submissions", "moderator_id", new_column_name="admin_id")
    op.alter_column("moderation_actions", "moderator_id", new_column_name="admin_id")

    op.drop_index("ix_submissions_moderator_id", table_name="submissions")
    op.create_index("ix_submissions_admin_id", "submissions", ["admin_id"], unique=False)

    op.drop_index("ix_moderation_actions_moderator_id", table_name="moderation_actions")
    op.create_index("ix_moderation_actions_admin_id", "moderation_actions", ["admin_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_moderation_actions_admin_id", table_name="moderation_actions")
    op.create_index("ix_moderation_actions_moderator_id", "moderation_actions", ["moderator_id"], unique=False)

    op.drop_index("ix_submissions_admin_id", table_name="submissions")
    op.create_index("ix_submissions_moderator_id", "submissions", ["moderator_id"], unique=False)

    op.alter_column("moderation_actions", "admin_id", new_column_name="moderator_id")
    op.alter_column("submissions", "admin_id", new_column_name="moderator_id")
