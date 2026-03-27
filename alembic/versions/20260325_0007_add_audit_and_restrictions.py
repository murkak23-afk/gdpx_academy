"""add admin audit and user restrictions

Revision ID: 20260325_0007
Revises: 20260325_0006
Create Date: 2026-03-25 00:00:07
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260325_0007"
down_revision = "20260325_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_restricted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("duplicate_timeout_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("captcha_answer", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("captcha_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_index("ix_users_is_restricted", "users", ["is_restricted"], unique=False)

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"], unique=False)
    op.create_index("ix_admin_audit_logs_admin_id", "admin_audit_logs", ["admin_id"], unique=False)
    op.create_index("ix_admin_audit_logs_target_id", "admin_audit_logs", ["target_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_target_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_admin_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")

    op.drop_index("ix_users_is_restricted", table_name="users")
    op.drop_column("users", "captcha_attempts")
    op.drop_column("users", "captcha_answer")
    op.drop_column("users", "duplicate_timeout_until")
    op.drop_column("users", "is_restricted")
