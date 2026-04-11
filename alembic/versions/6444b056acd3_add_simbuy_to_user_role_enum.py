"""add_simbuy_to_user_role_enum

Revision ID: 6444b056acd3
Revises: cd5fbb1d88b9
Create Date: 2026-04-09 15:21:54.975934
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6444b056acd3'
down_revision = 'cd5fbb1d88b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем значение 'simbuy' в тип 'user_role_enum'
    # В PostgreSQL ALTER TYPE ADD VALUE не может быть выполнено внутри транзакционного блока в некоторых версиях,
    # но Alembic справляется с этим через op.execute.
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'simbuy'")


def downgrade() -> None:
    # Удаление значения из ENUM в PG требует пересоздания типа, что сложно и опасно.
    pass
