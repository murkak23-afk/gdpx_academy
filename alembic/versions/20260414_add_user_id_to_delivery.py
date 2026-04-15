"""add_user_id_to_delivery_configs

Revision ID: 20260414_add_user_id_to_delivery
Revises: de3b499ec34a
Create Date: 2026-04-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260414_add_user_id_to_delivery'
down_revision: Union[str, None] = 'de3b499ec34a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавляем колонку user_id в delivery_configs
    op.add_column('delivery_configs', sa.Column('user_id', sa.BigInteger(), nullable=True))
    
    # 2. Создаем индекс для быстрого поиска
    op.create_index(op.f('ix_delivery_configs_user_id'), 'delivery_configs', ['user_id'], unique=False)
    
    # 3. Добавляем Foreign Key
    op.create_foreign_key('fk_delivery_configs_user_id', 'delivery_configs', 'users', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('fk_delivery_configs_user_id', 'delivery_configs', type_='foreignkey')
    op.drop_index(op.f('ix_delivery_configs_user_id'), table_name='delivery_configs')
    op.drop_column('delivery_configs', 'user_id')
