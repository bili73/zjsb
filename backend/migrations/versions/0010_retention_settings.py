"""Add shared retention without rebuilding tasks or cascading history."""
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE retention_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        days INTEGER CHECK (days IS NULL OR days IN (7,15,30)),
        revision INTEGER NOT NULL CHECK (revision >= 0))''')
    op.execute('INSERT INTO retention_settings VALUES (1,7,0)')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
