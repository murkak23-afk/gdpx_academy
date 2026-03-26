"""Daily forward counts per admin chat (UTC).

Revision ID: 0012
Revises: 20260326_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_0012"
down_revision = "20260326_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_chat_forward_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_chat_id", sa.Integer(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("forward_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_chat_id"],
            ["admin_chats.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admin_chat_id", "stat_date", name="uq_admin_chat_forward_day"),
    )
    op.create_index("ix_admin_chat_forward_daily_admin_chat_id", "admin_chat_forward_daily", ["admin_chat_id"])
    op.create_index("ix_admin_chat_forward_daily_stat_date", "admin_chat_forward_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_table("admin_chat_forward_daily")
