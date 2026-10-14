"""Add self-owned presentation preferences without changing existing records."""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE workbench_preferences (
        user_id TEXT PRIMARY KEY REFERENCES web_users(id) ON DELETE CASCADE,
        layout_json TEXT, revision INTEGER NOT NULL CHECK (revision >= 1))''')
    op.execute('''CREATE TABLE workbench_default (
        id INTEGER PRIMARY KEY CHECK (id = 1), layout_json TEXT,
        revision INTEGER NOT NULL CHECK (revision >= 1))''')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
