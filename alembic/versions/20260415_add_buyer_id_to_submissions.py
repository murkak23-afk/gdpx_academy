"""add_buyer_id_to_submissions

Revision ID: 20260415_add_buyer_id_to_submissions
Revises: 20260414_add_user_id_to_delivery
Create Date: 2026-04-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260415_add_buyer_id_to_submissions'
down_revision: Union[str, None] = '20260414_add_user_id_to_delivery'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавляем колонку buyer_id в submissions
    op.add_column('submissions', sa.Column('buyer_id', sa.BigInteger(), nullable=True))
    
    # 2. Создаем индекс для быстрого поиска активов симбайера
    op.create_index(op.f('ix_submissions_buyer_id'), 'submissions', ['buyer_id'], unique=False)
    
    # 3. Добавляем Foreign Key на таблицу users
    op.create_foreign_key('fk_submissions_buyer_id', 'submissions', 'users', ['buyer_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_submissions_buyer_id', 'submissions', type_='foreignkey')
    op.drop_index(op.f('ix_submissions_buyer_id'), table_name='submissions')
    op.drop_column('submissions', 'buyer_id')
