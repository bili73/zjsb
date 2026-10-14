"""Account-owned presentation preferences with optimistic concurrency."""
import json
from sqlalchemy import text
from .task_store import TaskError


def load_layout(connection, user_id):
    row = connection.execute(text('SELECT layout_json,revision FROM workbench_preferences WHERE user_id=:id'),
                             {'id': user_id}).mappings().first()
    return dict(layout=json.loads(row['layout_json']) if row['layout_json'] is not None else None,
                revision=row['revision']) if row else dict(layout=None, revision=0)


def save_layout(connection, user_id, layout, expected_revision):
    current = load_layout(connection, user_id)
    if current['revision'] != expected_revision:
        raise TaskError('WORKBENCH_VERSION_CONFLICT', '此账号的布局已在其他页面修改，请重新读取后再调整', 409)
    if current['layout'] == layout:
        return current
    result = dict(layout=layout, revision=current['revision'] + 1)
    connection.execute(text('''INSERT INTO workbench_preferences(user_id,layout_json,revision)
        VALUES (:id,:layout,:revision) ON CONFLICT(user_id) DO UPDATE
        SET layout_json=excluded.layout_json,revision=excluded.revision'''),
        dict(id=user_id, layout=json.dumps(layout) if layout is not None else None, revision=result['revision']))
    return result


def load_default(connection):
    row = connection.execute(text('SELECT layout_json,revision FROM workbench_default WHERE id=1')).mappings().first()
    return dict(layout=json.loads(row['layout_json']) if row['layout_json'] is not None else None,
                revision=row['revision']) if row else dict(layout=None, revision=0)


def load_preferences(connection, user_id):
    return dict(load_layout(connection, user_id), defaults=load_default(connection))


def save_default(connection, layout, expected_revision):
    current = load_default(connection)
    if current['revision'] != expected_revision:
        raise TaskError('WORKBENCH_DEFAULT_VERSION_CONFLICT', '默认布局已被其他管理员修改，请重新读取后再调整', 409)
    if current['layout'] == layout:
        return current
    result = dict(layout=layout, revision=current['revision'] + 1)
    connection.execute(text('''INSERT INTO workbench_default(id,layout_json,revision)
        VALUES (1,:layout,:revision) ON CONFLICT(id) DO UPDATE
        SET layout_json=excluded.layout_json,revision=excluded.revision'''),
        dict(layout=json.dumps(layout) if layout is not None else None, revision=result['revision']))
    return result
