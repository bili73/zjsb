"""Fence one active run while its owned processes stop outside a write lock."""
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE tasks ADD COLUMN stop_code TEXT')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
