"""add_esim_indexes

Revision ID: 13d9df81ab4b
Revises: b64ea96a73bc
Create Date: 2026-04-05 18:37:49.959439
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13d9df81ab4b'
down_revision = 'b64ea96a73bc'
branch_labels = None
depends_on = None


def upgrade() -> None:
     #op.create_index('ix_submissions_status', 'submissions', ['status'])
     #op.create_index('ix_submissions_user_id', 'submissions', ['user_id'])
     op.create_index('ix_submissions_assigned_at', 'submissions', ['assigned_at'])

def downgrade() -> None:
    op.drop_index('ix_submissions_status', 'submissions')
    op.drop_index('ix_submissions_user_id', 'submissions')
    op.drop_index('ix_submissions_assigned_at', 'submissions')