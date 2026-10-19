"""Version-bound original evidence and bounded display previews."""
from io import BytesIO
import json
from sqlalchemy import text
from PIL import Image

from .task_store import TaskError, identity, now
from .review import reason, optional_reason, invalid


def corrected_preview(store, task_id, run_id, revision, page, *, actor, role, masked=True, access_reason=None, user=None, authorize=None, rendition='original'):
    if type(page) is not int or page < 1:
        invalid()
    if rendition not in {'original', 'display'}:
        invalid('预览图版本无效')
    with store.engine.connect() as connection:
        if authorize:
            authorize(connection)
        row = store._row(connection, task_id, user)
        store._expected(row, run_id, revision)
        if role not in {'operator', 'admin'}:
            raise TaskError('FORBIDDEN_REVEAL', '当前账号无完整预览权限', 403)
        optional_reason(access_reason)
        artifacts = connection.execute(text("SELECT * FROM artifacts WHERE task_id=:task AND run_id=:run AND kind='corrected' AND page_index=:page"),
                                       dict(task=task_id, run=run_id, page=page)).mappings().all()
        if len(artifacts) != 1:
            raise TaskError('INVALID_REQUEST', '该页没有可唯一定位的原件证据', 404)
        source_reference = artifacts[0]['reference']
    data = store.storage.read(source_reference)
    # Re-encode metadata-free pixels; content must have passed admission safety.
    target = BytesIO()
    with Image.open(BytesIO(data)) as image:
        pixels = image.convert('RGB')
        pixels.info.clear()
        if rendition == 'display':
            pixels.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        pixels.save(target, format='PNG')
    history = dict(event='preview_full', actor=actor, reason=access_reason, at=now(),
                   run_id=run_id, result_revision=revision, page=page)
    reference = store.storage.put(json.dumps(history, ensure_ascii=False).encode())
    try:
        with store.transaction() as connection:
            if authorize:
                authorize(connection)
            row = store._row(connection, task_id, user)
            store._expected(row, run_id, revision)
            store._audit(connection, 'preview_full', actor, row, result_revision=revision, page=page)
            connection.execute(text("INSERT INTO artifacts(id,task_id,run_id,kind,reference) VALUES (:id,:task,:run,'access_history',:ref)"),
                               dict(id=identity(), task=task_id, run=run_id, ref=reference))
    except BaseException:
        store.storage.delete(reference)
        raise
    return target.getvalue()


def reveal_fields(store, task_id, body, actor, role, *, user=None, authorize=None):
    if role not in {'operator', 'admin'}:
        raise TaskError('FORBIDDEN_REVEAL', '当前账号无完整值查看权限', 403)
    if not isinstance(body, dict) or set(body) != {'run_id', 'expected_revision', 'fields', 'reason'}:
        invalid()
    reason(body['reason'])
    keys = body['fields']
    allowed = {'id_number', 'card_number', 'phone', 'certificate_no', 'report_no', 'passport_number', 'household_no', 'verification_code', 'online_verification_code', 'unified_social_credit_code'}
    if not isinstance(keys, list) or not keys or any(not isinstance(key, str) or key not in allowed for key in keys) or len(set(keys)) != len(keys):
        invalid('仅允许查看本次明确指定的敏感字段')
    with store.transaction() as connection:
        if authorize:
            authorize(connection)
        row = store._row(connection, task_id, user)
        store._expected(row, body['run_id'], body['expected_revision'])
        result = store.storage.unpack(row['result_enc'])
        if not result:
            raise TaskError('INVALID_STATE', '当前无可用结果')
        fields = {field['key']: field.get('value') for field in result.get('fields', [])}
        if set(keys) - fields.keys():
            invalid('指定字段不属于该结果')
        store._audit(connection, 'reveal', actor, row, result_revision=row['revision'], fields=keys)
        store._access_history(connection, row, actor, 'reveal', body['reason'], fields=keys)
        return dict(fields={key: fields[key] for key in keys}, expires_in=60)
