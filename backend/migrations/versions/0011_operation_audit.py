"""Add operation outcomes and encrypted attribution without rewriting legacy audit."""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        'version INTEGER NOT NULL DEFAULT 0', "outcome TEXT NOT NULL DEFAULT 'legacy'",
        'batch_id TEXT', 'target_type TEXT', 'target_id TEXT', 'request_id TEXT',
        'actor_snapshot_enc BLOB', 'context_enc BLOB',
    ):
        op.execute('ALTER TABLE audit ADD COLUMN ' + column)
    op.execute('CREATE INDEX audit_time ON audit(created_at DESC,id DESC)')
    op.execute('CREATE INDEX audit_actor_time ON audit(actor,created_at DESC,id DESC)')
    op.execute('CREATE INDEX audit_batch_time ON audit(batch_id,created_at DESC,id DESC)')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
