"""initial schema

Revision ID: 20260325_0001
Revises: None
Create Date: 2026-03-25 00:00:01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260325_0001"
down_revision = None
branch_labels = None
depends_on = None


user_role_enum = sa.Enum("seller", "moderator", "chief_admin", name="user_role_enum")
user_language_enum = sa.Enum("ru", "en", "pl", name="user_language_enum")
submission_status_enum = sa.Enum(
    "pending",
    "in_review",
    "rejected",
    "accepted",
    "blocked",
    "not_a_scan",
    name="submission_status_enum",
)
rejection_reason_enum = sa.Enum(
    "duplicate",
    "quality",
    "rules_violation",
    "other",
    name="rejection_reason_enum",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("language", user_language_enum, nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("payout_details", sa.String(length=512), nullable=True),
        sa.Column("pending_balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_paid", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payout_rate", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("moderator_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=False),
        sa.Column("file_unique_id", sa.String(length=255), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("description_text", sa.Text(), nullable=False),
        sa.Column("status", submission_status_enum, nullable=False),
        sa.Column("rejection_reason", rejection_reason_enum, nullable=True),
        sa.Column("rejection_comment", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.ForeignKeyConstraint(["moderator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_category_id", "submissions", ["category_id"], unique=False)
    op.create_index("ix_submissions_file_unique_id", "submissions", ["file_unique_id"], unique=False)
    op.create_index("ix_submissions_image_sha256", "submissions", ["image_sha256"], unique=False)
    op.create_index("ix_submissions_moderator_id", "submissions", ["moderator_id"], unique=False)
    op.create_index("ix_submissions_status", "submissions", ["status"], unique=False)
    op.create_index("ix_submissions_user_id", "submissions", ["user_id"], unique=False)

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("moderator_id", sa.Integer(), nullable=True),
        sa.Column("from_status", submission_status_enum, nullable=True),
        sa.Column("to_status", submission_status_enum, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["moderator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_moderation_actions_moderator_id",
        "moderation_actions",
        ["moderator_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_actions_submission_id",
        "moderation_actions",
        ["submission_id"],
        unique=False,
    )

    op.create_table(
        "publication_archives",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("archive_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_message_id", sa.Integer(), nullable=False),
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id"),
    )
    op.create_index(
        "ix_publication_archives_submission_id",
        "publication_archives",
        ["submission_id"],
        unique=False,
    )

    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("paid_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["paid_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payouts_period_key", "payouts", ["period_key"], unique=False)
    op.create_index("ix_payouts_user_id", "payouts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payouts_user_id", table_name="payouts")
    op.drop_index("ix_payouts_period_key", table_name="payouts")
    op.drop_table("payouts")

    op.drop_index("ix_publication_archives_submission_id", table_name="publication_archives")
    op.drop_table("publication_archives")

    op.drop_index("ix_moderation_actions_submission_id", table_name="moderation_actions")
    op.drop_index("ix_moderation_actions_moderator_id", table_name="moderation_actions")
    op.drop_table("moderation_actions")

    op.drop_index("ix_submissions_user_id", table_name="submissions")
    op.drop_index("ix_submissions_status", table_name="submissions")
    op.drop_index("ix_submissions_moderator_id", table_name="submissions")
    op.drop_index("ix_submissions_image_sha256", table_name="submissions")
    op.drop_index("ix_submissions_file_unique_id", table_name="submissions")
    op.drop_index("ix_submissions_category_id", table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_categories_slug", table_name="categories")
    op.drop_table("categories")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")

    # Типы ENUM будут удалены вместе с откатом соответствующих таблиц.
