"""Seller daily upload quotas (requests).

Revision ID: 0010
Revises: 20260326_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_0010"
down_revision = "20260326_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_daily_quotas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quota_date", sa.Date(), nullable=False),
        sa.Column("max_uploads", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "quota_date", name="uq_seller_quota_user_day"),
    )
    op.create_index("ix_seller_daily_quotas_user_id", "seller_daily_quotas", ["user_id"], unique=False)
    op.create_index("ix_seller_daily_quotas_quota_date", "seller_daily_quotas", ["quota_date"], unique=False)


def downgrade() -> None:
    op.drop_table("seller_daily_quotas")
