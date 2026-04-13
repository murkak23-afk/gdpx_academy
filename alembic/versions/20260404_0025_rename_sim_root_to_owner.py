"""Rename sim_root → owner in UserRole enum and promote all admins to owner.

Revision ID: 20260404_0025
Revises: 20260404_0024
Create Date: 2026-04-04 00:00:02

What this migration does
────────────────────────
1. Adds the new 'owner' label to the PostgreSQL user_role_enum type.
   Uses IF NOT EXISTS so the statement is idempotent on fresh installs
   (where the squashed migration already creates the enum with 'owner').

2. Promotes every existing user whose role is currently 'admin', 'chief_admin',
   or the legacy 'sim_root' to the new 'owner' role.
   This fulfils the requirement: "all current admins become owners".

3. Downgrade: reverts promoted users back to 'admin'.
   The 'owner' label cannot be removed from the PostgreSQL enum without
   dropping and recreating the type, so it stays as an unused value after
   downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260404_0025"
down_revision = "20260404_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: add 'owner' to the enum type (no-op if already present).
    # Raw SQL is required because SQLAlchemy / Alembic have no helper for
    # ALTER TYPE … ADD VALUE with IF NOT EXISTS.
    # PostgreSQL requires commit before using a newly added enum value in DML.
    with op.get_context().autocommit_block():
        op.execute(sa.text("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'owner'"))

    # Step 2: promote all current admins (and legacy sim_root) to owner.
    op.execute(
        sa.text(
            "UPDATE users SET role = 'owner' "
            "WHERE role::text IN ('admin', 'chief_admin', 'sim_root')"
        )
    )


def downgrade() -> None:
    # Revert owner → admin.  'owner' stays in the enum as an unused value
    # because PostgreSQL does not support DROP VALUE on enum types.
    op.execute(
        sa.text("UPDATE users SET role = 'admin' WHERE role = 'owner'")
    )
