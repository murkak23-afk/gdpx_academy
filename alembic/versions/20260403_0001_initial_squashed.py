"""initial squashed schema

All prior migrations (0001–0023 + e9fa/2368) squashed into a single
initial migration that creates the full schema from scratch.

Revision ID: 20260403_0001
Revises: None
Create Date: 2026-04-03 00:00:01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260403_0001"
down_revision = None
branch_labels = None
depends_on = None

# ── Enum types ──────────────────────────────────────────────────────
user_role_enum = sa.Enum("seller", "admin", "sim_root", name="user_role_enum")
user_language_enum = sa.Enum("ru", name="user_language_enum")
submission_status_enum = sa.Enum(
    "pending", "in_review", "rejected", "accepted", "blocked", "not_a_scan",
    name="submission_status_enum",
)
rejection_reason_enum = sa.Enum(
    "duplicate", "quality", "rules_violation", "other",
    name="rejection_reason_enum",
)
payout_status_enum = sa.Enum("pending", "paid", "cancelled", name="payout_status_enum")


def upgrade() -> None:
    # ── users ───────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("language", user_language_enum, nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_restricted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("duplicate_timeout_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captcha_answer", sa.String(16), nullable=True),
        sa.Column("captcha_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("payout_details", sa.String(512), nullable=True),
        sa.Column("pending_balance", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("total_paid", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_is_restricted", "users", ["is_restricted"])

    # ── categories ──────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("photo_file_id", sa.String(256), nullable=True),
        sa.Column("payout_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_upload_limit", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("operator", sa.String(60), nullable=True),
        sa.Column("sim_type", sa.String(60), nullable=True),
        sa.Column("hold_condition", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"])

    # ── submissions ─────────────────────────────────────────────────
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("telegram_file_id", sa.String(255), nullable=False),
        sa.Column("file_unique_id", sa.String(255), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("attachment_type", sa.String(16), nullable=False, server_default=sa.text("'photo'")),
        sa.Column("description_text", sa.Text(), nullable=False),
        sa.Column("phone_normalized", sa.String(32), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_status_change", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", submission_status_enum, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("rejection_reason", rejection_reason_enum, nullable=True),
        sa.Column("rejection_comment", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("hold_assigned", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_user_id", "submissions", ["user_id"])
    op.create_index("ix_submissions_admin_id", "submissions", ["admin_id"])
    op.create_index("ix_submissions_category_id", "submissions", ["category_id"])
    op.create_index("ix_submissions_file_unique_id", "submissions", ["file_unique_id"])
    op.create_index("ix_submissions_image_sha256", "submissions", ["image_sha256"])
    op.create_index("ix_submissions_attachment_type", "submissions", ["attachment_type"])
    op.create_index("ix_submissions_phone_normalized", "submissions", ["phone_normalized"])
    op.create_index("ix_submissions_status", "submissions", ["status"])

    # ── review_actions ──────────────────────────────────────────────
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_status", submission_status_enum, nullable=True),
        sa.Column("to_status", submission_status_enum, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_actions_submission_id", "review_actions", ["submission_id"])
    op.create_index("ix_review_actions_admin_id", "review_actions", ["admin_id"])

    # ── publication_archives ────────────────────────────────────────
    op.create_table(
        "publication_archives",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("archive_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_message_id", sa.BigInteger(), nullable=False),
        sa.Column("archived_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publication_archives_submission_id", "publication_archives", ["submission_id"], unique=True)

    # ── payouts ─────────────────────────────────────────────────────
    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(20), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=True),
        sa.Column("status", payout_status_enum, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("uploaded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("not_a_scan_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("crypto_check_id", sa.String(128), nullable=True),
        sa.Column("crypto_check_url", sa.String(512), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by_admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cancelled_by_admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cancel_reason", sa.String(255), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payouts_user_id", "payouts", ["user_id"])
    op.create_index("ix_payouts_period_key", "payouts", ["period_key"])
    op.create_index("ix_payouts_period_date", "payouts", ["period_date"])
    op.create_index("ix_payouts_status", "payouts", ["status"])
    op.create_index("ix_payouts_category_id", "payouts", ["category_id"])
    op.create_index("ix_payouts_crypto_check_id", "payouts", ["crypto_check_id"])

    # ── admin_audit_logs ────────────────────────────────────────────
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_logs_admin_id", "admin_audit_logs", ["admin_id"])
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index("ix_admin_audit_logs_target_id", "admin_audit_logs", ["target_id"])

    # ── seller_daily_quotas ─────────────────────────────────────────
    op.create_table(
        "seller_daily_quotas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quota_date", sa.Date(), nullable=False),
        sa.Column("max_uploads", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "category_id", "quota_date", name="uq_seller_cat_quota_day"),
    )
    op.create_index("ix_seller_daily_quotas_user_id", "seller_daily_quotas", ["user_id"])
    op.create_index("ix_seller_daily_quotas_category_id", "seller_daily_quotas", ["category_id"])
    op.create_index("ix_seller_daily_quotas_quota_date", "seller_daily_quotas", ["quota_date"])

    # ── admin_chat_forward_daily ────────────────────────────────────
    op.create_table(
        "admin_chat_forward_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("forward_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id", "stat_date", name="uq_forward_daily_tgchat_day"),
    )
    op.create_index("ix_admin_chat_forward_daily_telegram_chat_id", "admin_chat_forward_daily", ["telegram_chat_id"])
    op.create_index("ix_admin_chat_forward_daily_stat_date", "admin_chat_forward_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_table("admin_chat_forward_daily")
    op.drop_table("seller_daily_quotas")
    op.drop_table("admin_audit_logs")
    op.drop_table("payouts")
    op.drop_table("publication_archives")
    op.drop_table("review_actions")
    op.drop_table("submissions")
    op.drop_table("categories")
    op.drop_table("users")
    payout_status_enum.drop(op.get_bind(), checkfirst=True)
    rejection_reason_enum.drop(op.get_bind(), checkfirst=True)
    submission_status_enum.drop(op.get_bind(), checkfirst=True)
    user_language_enum.drop(op.get_bind(), checkfirst=True)
    user_role_enum.drop(op.get_bind(), checkfirst=True)
