"""Persist account rotation and document enqueue order without rewriting results."""
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE tasks ADD COLUMN enqueue_seq INTEGER NOT NULL DEFAULT 0')
    op.execute('ALTER TABLE tasks ADD COLUMN queued_at TEXT')
    # Reruns retain created_at; updated_at is the best surviving enqueue marker.
    # Historical tied timestamps have no recoverable original input order.
    op.execute('''WITH ordered AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY
            CASE WHEN status='QUEUED' THEN updated_at ELSE created_at END,id) AS seq FROM tasks
    ) UPDATE tasks SET enqueue_seq=(SELECT seq FROM ordered WHERE ordered.id=tasks.id)''')
    # Approximate legacy ordering is useful; it is not an observed enqueue time.
    # Leave queued_at NULL rather than display creation time as a rerun timestamp.
    op.execute('CREATE INDEX tasks_enqueue ON tasks(enqueue_seq)')
    op.execute('''CREATE TABLE document_queue_cursors (
        lane TEXT PRIMARY KEY, last_owner TEXT NOT NULL)''')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
