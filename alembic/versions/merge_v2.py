"""merge_v2

Revision ID: merge_v2
Revises: 20260415_add_buyer_id_to_submissions, 9fca296304e5
Create Date: 2026-04-15 13:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'merge_v2'
down_revision: Union[str, Sequence[str], None] = (
    '20260415_add_buyer_id_to_submissions', 
    '9fca296304e5'
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
