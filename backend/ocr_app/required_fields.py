"""One shared required-field policy, projected onto immutable saved results."""
from copy import deepcopy
import json

from sqlalchemy import text

from .doc_profiles import PROFILES, LABELS, profile, member_profile, generic_required


def load_policy(connection):
    row = connection.execute(text('SELECT revision,overrides_json FROM required_field_settings WHERE id=1')).first()
    return dict(revision=row[0], overrides=json.loads(row[1])) if row else dict(revision=0, overrides={})


def configurable_fields(kind, overrides=None):
    fields = profile(kind, required_overrides=overrides)
    if kind == 'HOUSEHOLD_REGISTER':
        fields += [dict(field, key='members.' + field['key'], label='成员 / ' + field['label'])
                   for field in member_profile(overrides)]
    if kind == 'GENERIC':
        fields.append(dict(key='generic.full_text', label='正文', required=generic_required(overrides), editable=True, type='string'))
    return fields


def configuration(policy):
    return dict(revision=policy['revision'], items=[dict(doc_type=kind, label=LABELS[kind],
                uses_defaults=kind not in policy['overrides'], fields=configurable_fields(kind, policy['overrides']))
                for kind in PROFILES if kind != 'TABLE'])


def save_configuration(store, body, actor, *, authorize):
    from .task_store import TaskError
    if (not isinstance(body, dict) or set(body) != {'doc_type', 'required_fields', 'expected_revision'}
            or type(body['expected_revision']) is not int or body['expected_revision'] < 0
            or not isinstance(body['doc_type'], str) or body['doc_type'] not in PROFILES or body['doc_type'] == 'TABLE'):
        raise TaskError('INVALID_REQUEST', '必填字段设置参数无效', 422)
    kind, selected = body['doc_type'], body['required_fields']
    allowed = [field['key'] for field in configurable_fields(kind) if field['editable']]
    if selected is not None and (not isinstance(selected, list) or any(not isinstance(key, str) or key not in allowed for key in selected)
                                 or len(selected) != len(set(selected))):
        raise TaskError('INVALID_REQUEST', '请选择当前材料的可填写字段，派生字段不能设为必填', 422)
    with store.transaction() as connection:
        authorize(connection)
        policy = load_policy(connection)
        if policy['revision'] != body['expected_revision']:
            raise TaskError('SETTINGS_VERSION_CONFLICT', '必填设置已被修改，请重新读取后再保存', 409)
        updated = deepcopy(policy['overrides'])
        previous = [field['key'] for field in configurable_fields(kind, policy['overrides']) if field['required']]
        if selected is None:
            updated.pop(kind, None)
        else:
            updated[kind] = [key for key in allowed if key in selected]
        if updated == policy['overrides']:
            return configuration(policy)
        policy = dict(revision=policy['revision'] + 1, overrides=updated)
        connection.execute(text('INSERT INTO required_field_settings(id,revision,overrides_json) VALUES (1,:revision,:value) '
                                'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,overrides_json=excluded.overrides_json'),
                           dict(revision=policy['revision'], value=json.dumps(updated)))
        store._audit(connection, 'required_fields_changed', actor, doc_type=kind,
                     required_fields=updated.get(kind), old_required_fields=previous,
                     required_fields_revision=policy['revision'])
        return configuration(policy)


def project_requirements(result, overrides):
    """Refresh metadata only; never change a recognized or manually saved value."""
    from .extraction import issue
    kind = result.get('doc_type')
    if kind not in PROFILES or 'fields' not in result:
        return result
    values = {field['key']: field.get('value') for field in result['fields']}
    definitions = profile(kind, values, overrides)

    def refresh(fields, definitions):
        indexed = {field['key']: field for field in fields}
        for meta in definitions:
            field = indexed.get(meta['key'])
            if field is None:
                field = dict(key=meta['key'], label=meta['label'], value=None, confidence=None,
                             confidence_method='unavailable', validation_checks=[], review_issues=[], need_review=False)
                fields.append(field)
            field.update(required=meta['required'], editable=meta['editable'])
            missing = meta['required'] and (field.get('value') is None or isinstance(field.get('value'), str) and not field['value'].strip())
            problems = field.setdefault('review_issues', [])
            if missing and not any(p['code'] == 'MISSING' for p in problems):
                problems.append(issue('MISSING', '必填字段未可靠提取。'))
            if not missing:
                field['review_issues'] = [p for p in problems if p['code'] != 'MISSING']
            field['need_review'] = bool(field['review_issues'])
            if field.get('review_reason') == 'MISSING' and not missing:
                field['review_reason'] = field['review_issues'][0]['code'] if field['review_issues'] else None

    refresh(result['fields'], definitions)
    if kind == 'MEDICAL_REPORT':
        result['basic_info'] = {field['key']: field for field in result['fields']}
    if kind == 'HOUSEHOLD_REGISTER':
        for member in result.get('members', []):
            fields = member.get('fields') if isinstance(member.get('fields'), list) else [v for v in member.values() if isinstance(v, dict) and 'key' in v]
            refresh(fields, member_profile(overrides))
            if not isinstance(member.get('fields'), list):
                member.update({field['key']: field for field in fields})
    result['required_field_keys'] = [field['key'] for field in definitions if field['required']]
    if kind == 'HOUSEHOLD_REGISTER':
        result['required_field_keys'] += ['members.' + field['key'] for field in member_profile(overrides) if field['required']]
    if kind == 'GENERIC' and generic_required(overrides):
        result['required_field_keys'].append('generic.full_text')
    return result
