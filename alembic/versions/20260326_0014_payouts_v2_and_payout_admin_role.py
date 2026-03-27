"""Payout v2 fields and admin roles.

Revision ID: 20260326_0014
Revises: 20260326_0013
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260326_0014"
down_revision = "20260326_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'admin'")
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'payout_admin'")
    op.execute("CREATE TYPE payout_status_enum AS ENUM ('pending', 'paid', 'cancelled')")

    op.add_column("payouts", sa.Column("period_date", sa.Date(), nullable=True))
    op.add_column(
        "payouts",
        sa.Column(
            "status",
            sa.Enum("pending", "paid", "cancelled", name="payout_status_enum"),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("payouts", sa.Column("uploaded_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payouts", sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payouts", sa.Column("not_a_scan_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payouts", sa.Column("category_id", sa.Integer(), nullable=True))
    op.add_column("payouts", sa.Column("unit_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("payouts", sa.Column("crypto_check_id", sa.String(length=128), nullable=True))
    op.add_column("payouts", sa.Column("crypto_check_url", sa.String(length=512), nullable=True))
    op.add_column("payouts", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payouts", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payouts", sa.Column("cancelled_by_admin_id", sa.Integer(), nullable=True))
    op.add_column("payouts", sa.Column("cancel_reason", sa.String(length=255), nullable=True))

    op.create_index("ix_payouts_period_date", "payouts", ["period_date"], unique=False)
    op.create_index("ix_payouts_status", "payouts", ["status"], unique=False)
    op.create_index("ix_payouts_category_id", "payouts", ["category_id"], unique=False)
    op.create_index("ix_payouts_crypto_check_id", "payouts", ["crypto_check_id"], unique=False)
    op.create_foreign_key(
        "fk_payouts_category_id_categories",
        "payouts",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_payouts_cancelled_by_admin_id_users",
        "payouts",
        "users",
        ["cancelled_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        "UPDATE payouts SET period_date = CAST(period_key AS DATE) "
        "WHERE period_key ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
    )
    op.execute("UPDATE payouts SET status = 'paid', paid_at = created_at WHERE paid_by_admin_id IS NOT NULL")
    op.execute("UPDATE payouts SET uploaded_count = accepted_count WHERE uploaded_count = 0")

    op.alter_column("payouts", "status", server_default=None)
    op.alter_column("payouts", "uploaded_count", server_default=None)
    op.alter_column("payouts", "blocked_count", server_default=None)
    op.alter_column("payouts", "not_a_scan_count", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_payouts_cancelled_by_admin_id_users", "payouts", type_="foreignkey")
    op.drop_constraint("fk_payouts_category_id_categories", "payouts", type_="foreignkey")
    op.drop_index("ix_payouts_crypto_check_id", table_name="payouts")
    op.drop_index("ix_payouts_category_id", table_name="payouts")
    op.drop_index("ix_payouts_status", table_name="payouts")
    op.drop_index("ix_payouts_period_date", table_name="payouts")

    op.drop_column("payouts", "cancel_reason")
    op.drop_column("payouts", "cancelled_by_admin_id")
    op.drop_column("payouts", "cancelled_at")
    op.drop_column("payouts", "paid_at")
    op.drop_column("payouts", "crypto_check_url")
    op.drop_column("payouts", "crypto_check_id")
    op.drop_column("payouts", "unit_price")
    op.drop_column("payouts", "category_id")
    op.drop_column("payouts", "not_a_scan_count")
    op.drop_column("payouts", "blocked_count")
    op.drop_column("payouts", "uploaded_count")
    op.drop_column("payouts", "status")
    op.drop_column("payouts", "period_date")

    op.execute("DROP TYPE payout_status_enum")
