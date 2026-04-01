"""merge chief_admin role into admin

Revision ID: 20260401_0023
Revises: 20260401_0022
Create Date: 2026-04-01

All chief_admin users become admin. The chief_admin enum value is removed.
"""

from alembic import op
from sqlalchemy import text

revision = "20260401_0023"
down_revision = "20260401_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Convert all chief_admin users to admin
    op.execute(text("UPDATE users SET role = 'admin' WHERE role = 'chief_admin'"))

    # 2. Recreate the enum without chief_admin
    op.execute(text("ALTER TYPE user_role_enum RENAME TO user_role_enum_old"))
    op.execute(text("CREATE TYPE user_role_enum AS ENUM ('seller', 'admin', 'sim_root')"))
    op.execute(
        text(
            "ALTER TABLE users "
            "ALTER COLUMN role TYPE user_role_enum USING role::text::user_role_enum"
        )
    )
    op.execute(text("DROP TYPE user_role_enum_old"))


def downgrade() -> None:
    # Restore the old enum with chief_admin
    op.execute(text("ALTER TYPE user_role_enum RENAME TO user_role_enum_old"))
    op.execute(
        text(
            "CREATE TYPE user_role_enum AS ENUM ('seller', 'admin', 'chief_admin', 'sim_root')"
        )
    )
    op.execute(
        text(
            "ALTER TABLE users "
            "ALTER COLUMN role TYPE user_role_enum USING role::text::user_role_enum"
        )
    )
    op.execute(text("DROP TYPE user_role_enum_old"))
