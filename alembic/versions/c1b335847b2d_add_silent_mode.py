"""add_silent_mode

Revision ID: c1b335847b2d
Revises: 20260419_1715
Create Date: 2026-04-20 01:54:08.643188
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1b335847b2d'
down_revision = '20260419_1715'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем колонку с дефолтным значением false для существующих строк
    op.add_column('users', sa.Column('is_silent_mode', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('users', 'is_silent_mode')
