"""One global, confirmed retention policy for existing and future material."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import text


def load_policy(connection):
    return dict(connection.execute(text('SELECT days,revision FROM retention_settings WHERE id=1')).mappings().one())


def deadline(created_at, days):
    # NOT NULL legacy storage: the finite value is dormant under never.
    return (datetime.fromisoformat(created_at) + timedelta(days=days or 7)).isoformat()


def configuration(connection):
    from .task_store import ACTIVE
    result = load_policy(connection)
    at = datetime.now(timezone.utc)
    rows = connection.execute(text('SELECT created_at,status FROM tasks')).mappings().all()
    impact = []
    for days in (7, 15, 30):
        aged = [row for row in rows if datetime.fromisoformat(row['created_at']) <= at - timedelta(days=days)]
        active = sum(row['status'] in ACTIVE for row in aged)
        impact.append(dict(days=days, eligible_count=len(aged)-active, active_count=active))
    return dict(result, impact=impact, assessed_at=at.isoformat())


def save_configuration(store, body, actor, *, authorize):
    from .task_store import TaskError
    if (not isinstance(body, dict) or set(body) != {'days', 'expected_revision', 'confirmed'}
            or body['days'] is not None and (type(body['days']) is not int or body['days'] not in (7, 15, 30))
            or type(body['expected_revision']) is not int or body['expected_revision'] < 0
            or body['confirmed'] is not True):
        raise TaskError('INVALID_REQUEST', '请选择7天、15天、30天或永不清除，并确认影响后保存', 422)
    with store.transaction() as connection:
        authorize(connection)
        current = load_policy(connection)
        if current['revision'] != body['expected_revision']:
            raise TaskError('RETENTION_VERSION_CONFLICT', '保留设置已被修改，请重新读取并确认', 409)
        if current['days'] != body['days']:
            revision = current['revision'] + 1
            if body['days'] is not None:
                rows = connection.execute(text('SELECT id,created_at FROM tasks')).mappings().all()
                if rows:
                    connection.execute(text('UPDATE tasks SET expires_at=:expires WHERE id=:id'),
                        [dict(id=row['id'], expires=deadline(row['created_at'], body['days'])) for row in rows])
            connection.execute(text('UPDATE retention_settings SET days=:days,revision=:revision WHERE id=1'),
                               dict(days=body['days'], revision=revision))
            store._audit(connection, 'retention_changed', actor, old_days=current['days'],
                         days=body['days'], retention_revision=revision)
        return configuration(connection)
