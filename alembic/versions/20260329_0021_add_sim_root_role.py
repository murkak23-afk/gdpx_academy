"""add sim_root role for group /sim operations

Revision ID: 20260329_0021
Revises: 20260329_0020
Create Date: 2026-03-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260329_0021"
down_revision = "20260329_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'sim_root'"))


def downgrade() -> None:
    # В PostgreSQL нельзя удалить значение enum напрямую.
    # При откате переводим sim_root в admin и пересоздаём enum без sim_root.
    conn = op.get_bind()
    conn.execute(text("UPDATE users SET role = 'admin' WHERE role = 'sim_root'"))
    conn.execute(text("ALTER TYPE user_role_enum RENAME TO user_role_enum_old"))
    conn.execute(
        text(
            """CREATE TYPE user_role_enum AS ENUM ('seller', 'admin', 'chief_admin')"""
        )
    )
    conn.execute(
        text(
            """ALTER TABLE users ALTER COLUMN role TYPE user_role_enum
               USING role::text::user_role_enum"""
        )
    )
    conn.execute(text("DROP TYPE user_role_enum_old"))
