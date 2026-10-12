"""Keep the latest legacy session and enforce one browser login per account."""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''DELETE FROM web_sessions WHERE EXISTS (
        SELECT 1 FROM web_sessions AS newer
        WHERE newer.user_id=web_sessions.user_id AND
          (newer.expires_at>web_sessions.expires_at OR
           (newer.expires_at=web_sessions.expires_at AND newer.token_hash>web_sessions.token_hash)))''')
    op.execute('CREATE UNIQUE INDEX uq_web_sessions_user ON web_sessions(user_id)')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
