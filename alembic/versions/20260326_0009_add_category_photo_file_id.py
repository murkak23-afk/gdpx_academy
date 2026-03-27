"""Add photo_file_id column to categories.

Revision ID: 0009
Revises: 20260325_0008_submission_attachment_type
"""

import sqlalchemy as sa

from alembic import op

revision = "20260326_0009"
# NOTE: keep revision chain consistent; down_revision is the revision id,
# not the filename. See 20260325_0008_submission_attachment_type.py.
down_revision = "20260325_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("photo_file_id", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "photo_file_id")
