"""alter telegram ids to biginteger

Revision ID: 2368fc78c9d8
Revises: e9fa0e8006a2
Create Date: 2026-03-27 04:03:34.937989
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '2368fc78c9d8'
down_revision = 'e9fa0e8006a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "publication_archives",
        "archive_message_id",
        existing_type=sa.INTEGER(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "publication_archives",
        "archive_message_id",
        existing_type=sa.BigInteger(),
        type_=sa.INTEGER(),
        existing_nullable=False,
    )
