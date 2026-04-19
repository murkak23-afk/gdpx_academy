from alembic import op
import sqlalchemy as sa

revision = '20260419_1715'
down_revision = '20260419_1655'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('support_tickets', sa.Column('admin_chat_id', sa.BigInteger(), nullable=True))
    op.add_column('support_tickets', sa.Column('admin_msg_id', sa.BigInteger(), nullable=True))

def downgrade():
    op.drop_column('support_tickets', 'admin_msg_id')
    op.drop_column('support_tickets', 'admin_chat_id')
