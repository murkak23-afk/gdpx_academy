"""rename moderation_actions table to review_actions

Revision ID: 20260325_0003
Revises: 20260325_0002
Create Date: 2026-03-25 00:00:03
"""
from __future__ import annotations

from alembic import op


revision = "20260325_0003"
down_revision = "20260325_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("moderation_actions", "review_actions")
    op.execute(
        "ALTER INDEX IF EXISTS ix_moderation_actions_admin_id "
        "RENAME TO ix_review_actions_admin_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_moderation_actions_submission_id "
        "RENAME TO ix_review_actions_submission_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX IF EXISTS ix_review_actions_submission_id "
        "RENAME TO ix_moderation_actions_submission_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_review_actions_admin_id "
        "RENAME TO ix_moderation_actions_admin_id"
    )
    op.rename_table("review_actions", "moderation_actions")
