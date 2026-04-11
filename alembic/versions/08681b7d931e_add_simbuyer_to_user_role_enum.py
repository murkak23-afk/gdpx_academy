"""add_simbuyer_to_user_role_enum

Revision ID: 08681b7d931e
Revises: 6444b056acd3
Create Date: 2026-04-09 22:11:59.543865
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '08681b7d931e'
down_revision = '6444b056acd3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'simbuyer'")


def downgrade() -> None:
    pass
