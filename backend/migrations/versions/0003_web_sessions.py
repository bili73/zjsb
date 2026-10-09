"""Add named accounts and revocable browser sessions without rewriting tasks."""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE web_users (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
        role TEXT NOT NULL, password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)''')
    op.execute('''CREATE TABLE web_sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES web_users(id),
        expires_at REAL NOT NULL)''')
    op.execute('CREATE INDEX web_sessions_user ON web_sessions(user_id)')
    op.execute('''CREATE TABLE login_attempts (
        client_hash TEXT PRIMARY KEY, window_start REAL NOT NULL, attempts INTEGER NOT NULL)''')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
