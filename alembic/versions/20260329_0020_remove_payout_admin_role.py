"""remove payout_admin role, consolidate to chief_admin

Revision ID: 20260329_0020
Revises: 20260328_0019
Create Date: 2026-03-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260329_0020"
down_revision = "20260328_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update any users with payout_admin role to chief_admin
    conn = op.get_bind()
    conn.execute(
        text("UPDATE users SET role = 'chief_admin' WHERE role = 'payout_admin'")
    )
    
    # Recreate the enum type without payout_admin
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


def downgrade() -> None:
    # Restore payout_admin to enum
    conn = op.get_bind()
    conn.execute(text("ALTER TYPE user_role_enum RENAME TO user_role_enum_old"))
    conn.execute(
        text(
            """CREATE TYPE user_role_enum AS ENUM ('seller', 'admin', 'chief_admin', 'payout_admin')"""
        )
    )
    conn.execute(
        text(
            """ALTER TABLE users ALTER COLUMN role TYPE user_role_enum 
               USING role::text::user_role_enum"""
        )
    )
    conn.execute(text("DROP TYPE user_role_enum_old"))
