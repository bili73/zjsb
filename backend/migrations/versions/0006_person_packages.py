"""Explicit encrypted person labels; legacy batches remain unassigned."""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE batches ADD COLUMN person_name_enc BLOB')
    op.execute('ALTER TABLE batches ADD COLUMN package_revision INTEGER NOT NULL DEFAULT 0')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
