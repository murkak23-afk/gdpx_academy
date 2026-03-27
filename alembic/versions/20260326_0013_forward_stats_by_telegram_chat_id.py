"""Forward stats by telegram_chat_id; drop admin_chats.

Revision ID: 0013
Revises: 20260326_0012
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260326_0013"
down_revision = "20260326_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_chat_forward_daily",
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
    )
    op.execute(
        """
        UPDATE admin_chat_forward_daily AS d
        SET telegram_chat_id = c.chat_id
        FROM admin_chats AS c
        WHERE d.admin_chat_id = c.id
        """
    )
    op.execute("DELETE FROM admin_chat_forward_daily WHERE telegram_chat_id IS NULL")
    op.execute(
        "ALTER TABLE admin_chat_forward_daily DROP CONSTRAINT IF EXISTS "
        "admin_chat_forward_daily_admin_chat_id_fkey"
    )
    op.drop_constraint("uq_admin_chat_forward_day", "admin_chat_forward_daily", type_="unique")
    op.drop_index("ix_admin_chat_forward_daily_admin_chat_id", table_name="admin_chat_forward_daily")
    op.drop_column("admin_chat_forward_daily", "admin_chat_id")
    op.alter_column("admin_chat_forward_daily", "telegram_chat_id", nullable=False)
    op.create_unique_constraint(
        "uq_forward_daily_tgchat_day",
        "admin_chat_forward_daily",
        ["telegram_chat_id", "stat_date"],
    )
    op.create_index(
        "ix_admin_chat_forward_daily_telegram_chat_id",
        "admin_chat_forward_daily",
        ["telegram_chat_id"],
        unique=False,
    )
    op.drop_table("admin_chats")


def downgrade() -> None:
    raise NotImplementedError("Откат 0013 не поддерживается: таблица admin_chats удалена.")
