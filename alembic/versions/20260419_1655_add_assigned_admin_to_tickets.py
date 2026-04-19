from alembic import op
import sqlalchemy as sa

revision = '20260419_1655'
down_revision = '9fca296304e5'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('support_tickets', sa.Column('assigned_admin_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))

def downgrade():
    op.drop_column('support_tickets', 'assigned_admin_id')
