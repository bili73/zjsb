"""Initial local task schema. Sensitive content is application-encrypted."""
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        '''CREATE TABLE batches (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, name_enc BLOB NOT NULL)''',
        '''CREATE TABLE tasks (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
            run_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
            progress INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, active_started_at TEXT, content_hash TEXT NOT NULL,
            doc_type TEXT NOT NULL, input_ref TEXT NOT NULL, meta_enc BLOB NOT NULL,
            options_enc BLOB NOT NULL, pages_enc BLOB, result_enc BLOB, warnings_enc BLOB,
            error_json TEXT, UNIQUE(batch_id,content_hash))''',
        '''CREATE INDEX tasks_queue ON tasks(status,created_at)''',
        '''CREATE TABLE runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            status TEXT NOT NULL, started_at TEXT, ended_at TEXT, result_enc BLOB, error_json TEXT)''',
        '''CREATE TABLE artifacts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL, kind TEXT NOT NULL, page_index INTEGER, width INTEGER, height INTEGER,
            reference TEXT NOT NULL)''',
        '''CREATE TABLE attempts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL, created_at TEXT NOT NULL, payload_enc BLOB NOT NULL)''',
        '''CREATE TABLE audit (id TEXT PRIMARY KEY, actor TEXT NOT NULL, task_id TEXT,
            run_id TEXT, event TEXT NOT NULL, created_at TEXT NOT NULL, detail_json TEXT NOT NULL)''',
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
