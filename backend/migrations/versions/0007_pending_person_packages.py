"""Package intent is independent of a confirmed, encrypted person label."""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE batches ADD COLUMN is_person_package INTEGER NOT NULL DEFAULT 0')
    op.execute('UPDATE batches SET is_person_package=1 WHERE person_name_enc IS NOT NULL')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
