"""Persist shared business-required fields without rewriting recognition history."""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE required_field_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL,
        overrides_json TEXT NOT NULL)''')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
