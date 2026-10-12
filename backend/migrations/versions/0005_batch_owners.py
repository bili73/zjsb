"""Preserve immutable uploading identities without assigning ambiguous history."""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    # No account FK: deleting a login must never delete or reassign its material.
    op.execute('ALTER TABLE batches ADD COLUMN owner_id TEXT')
    op.execute('ALTER TABLE batches ADD COLUMN owner_snapshot_enc BLOB')
    op.execute('''UPDATE batches SET owner_id=(
        SELECT NULLIF(MIN(a.actor),'') FROM tasks t
        JOIN audit a ON a.task_id=t.id AND a.event='task_created'
        WHERE t.batch_id=batches.id
        HAVING COUNT(DISTINCT a.actor)=1 AND COUNT(DISTINCT t.id)=(
            SELECT COUNT(*) FROM tasks original WHERE original.batch_id=batches.id))''')
    op.execute('CREATE INDEX batches_owner_created ON batches(owner_id,created_at DESC,id)')


def downgrade():
    raise RuntimeError('Destructive downgrade is not supported; restore a verified backup.')
