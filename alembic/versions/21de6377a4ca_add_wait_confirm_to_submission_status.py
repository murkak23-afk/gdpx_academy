"""add_wait_confirm_to_submission_status

Revision ID: 21de6377a4ca
Revises: de3b499ec34a
Create Date: 2026-04-11 16:08:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '21de6377a4ca'
down_revision = '08681b7d931e'
branch_labels = None
depends_on = None


def upgrade():
    # Добавление значения в ENUM (PostgreSQL специфично)
    # Используем транзакционный обход, так как ALTER TYPE ADD VALUE нельзя в блоке транзакции в старых PG
    op.execute("COMMIT")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE 'wait_confirm'")


def downgrade():
    # В PG нельзя просто удалить значение из ENUM
    pass
