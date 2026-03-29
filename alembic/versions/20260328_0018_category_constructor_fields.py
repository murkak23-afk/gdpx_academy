"""Конструктор категорий: operator, sim_type, hold_condition.

Revision ID: 20260328_0018
Revises: e9fa0e8006a2
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "20260328_0018"
down_revision = "20260327_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("operator", sa.String(60), nullable=True))
    op.add_column("categories", sa.Column("sim_type", sa.String(60), nullable=True))
    op.add_column("categories", sa.Column("hold_condition", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "hold_condition")
    op.drop_column("categories", "sim_type")
    op.drop_column("categories", "operator")
