"""Explicit export disputes, independent of informational review flags."""
from functools import lru_cache
import hashlib
import json
import re

from .bank_bins import _data, normalize_pan
from .doc_profiles import profile, BANK_CARD_TYPES
from .validation import validate_field, ID_CHECKSUM_LEGACY_MESSAGE, ID_CHECKSUM_FAILURE_MESSAGE

DISPUTE_CODES = {'VALIDATION_FAILED', 'CONFLICT', 'MULTI_CANDIDATES', 'LOW_CONFIDENCE'}


@lru_cache(maxsize=1)
def bank_length_reference():
    rows, names = _data()
    groups = {}
    for row in rows:
        groups.setdefault(row['bin'], []).append(row)
    return {prefix: sorted({int(row['length']) for row in group}) if
            len({(r['bank'], r['type']) for r in group}) == 1 and
            all(r['bank'] in names and r['type'] in {'DC', 'CC', 'SCC', 'PC'} for r in group)
            else None for prefix, group in groups.items()}


def number_length_warning(kind, key, value):
    """Warning-level counterpart of numberLengthHint; never changes a value."""
    if not isinstance(value, str):
        return None
    compact = normalize_pan(value) if key == 'card_number' else re.sub(r'\s', '', value)
    length = len(compact)
    if not length:
        return None
    if key == 'id_number' or kind == 'BUSINESS_LICENSE' and key == 'unified_social_credit_code':
        if length != 18:
            return f'当前为{length}位，比18位{"多" if length > 18 else "少"}{abs(length-18)}位；请对照原件核对。'
    elif kind in BANK_CARD_TYPES and key == 'card_number':
        if not 10 <= length <= 19:
            return f'卡号当前为{length}位，超出本系统10–19位兼容范围；请对照原件核对。'
        try:
            reference = bank_length_reference()
        except (OSError, ValueError, KeyError):
            return None  # Unavailable reference is not evidence of a dispute.
        prefix = max((p for p in reference if compact.isascii() and compact.isdigit() and compact.startswith(p)), key=len, default='')
        lengths = reference.get(prefix) if len(prefix) in {6, 8} else None
        if lengths and length not in lengths:
            return f'卡号当前为{length}位，离线前缀参考长度为{"或".join(map(str, lengths))}位；资料可能过时，请核对原件。'
    elif key == 'certificate_no':
        if kind in {'DIPLOMA', 'XUEXIN_DIPLOMA_TABLE'} and length > 18:
            return f'证书编号当前为{length}位，高等教育学历编号常见17或18位；早期或其他编号以原件为准。'
        if kind == 'DEGREE_CERT' and length > (17 if compact[:1].upper() in {'T', 'Z'} else 16):
            return f'学位证书编号当前为{length}位，普通编号参考16位，历史T/Z前缀可为17位；特殊编号以原件为准。'
    elif kind == 'XUEXIN_DIPLOMA_TABLE' and key == 'online_verification_code' and length not in {12, 16}:
        return f'在线验证码当前为{length}位，与本系统12或16位兼容规则不符；请核对原件。'
    return None


def _fields(result):
    fields = dict(result.get('basic_info', {}))
    fields.update({f['key']: f for f in result.get('fields', [])})
    keys = {f['key'] for f in profile(result['doc_type'])}
    return [f for key, f in fields.items() if key in keys and isinstance(f, dict)]


def _semantic(value):
    """Exclude review bookkeeping so an ordinary save cannot change an issue ID."""
    if isinstance(value, dict):
        return {k: _semantic(v) for k, v in value.items() if k in {
            'key', 'value', 'absence_reason', 'candidates', 'source', 'raw_text', 'page',
            'name', 'result_raw', 'unit', 'reference_range', 'risk_grade', 'diagnosis',
            'reported_abnormal_marker', 'item_id', 'finding_id', 'member_id', 'text',
            'result_item_id', 'scope', 'declared_count', 'findings', 'full_text', 'key_values'}}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    return value


def export_disputes(result, *, include_confirmed=False):
    if not result or result.get('doc_type') == 'TABLE':
        return []
    kind = result['doc_type']
    fields = _fields(result)
    values = {f['key']: f.get('value') for f in fields}
    targets = [('task', '材料一致性', result, None, {})]
    targets.extend((f['key'], f.get('label', f['key']), f, f['key'], values) for f in fields)
    from .extraction import medical_exclusion_reason
    for index, item in enumerate(result.get('items', [])):
        if kind == 'MEDICAL_REPORT' and medical_exclusion_reason(item.get('name')):
            continue
        targets.append((f'items[{index}]', f'检测项目：{item.get("name", "未命名")}', item, None, {}))
    for index, finding in enumerate(result.get('report_summary', {}).get('findings', [])):
        targets.append((f'report_summary.findings[{index}]', f'报告清单第{index+1}项', finding, None, {}))
    for index, member in enumerate(result.get('members', [])):
        entries = member['fields'] if isinstance(member.get('fields'), list) else [v for v in member.values() if isinstance(v, dict) and 'key' in v]
        context = {f['key']: f.get('value') for f in entries}
        targets.extend((f'members[{index}].{f["key"]}', f'成员{index+1}：{f.get("label", f["key"])}', f, f['key'], context) for f in entries)
    confirmed = {c['dispute_id'] for c in result.get('_export_confirmations', [])}
    items = {item.get('item_id'): item for item in result.get('items', []) if item.get('item_id')}
    def present(value):
        return value is not None and str(value).strip() != ''

    output = []
    for path, label, target, key, context in targets:
        can_confirm = present(target.get('value')) if key else True
        if kind == 'MEDICAL_REPORT' and path.startswith('items['):
            can_confirm = present(target.get('result_raw')) and (
                not target.get('diagnosis_sources') or present(target.get('diagnosis')) or
                bool(target.get('absence_reasons', {}).get('diagnosis')))
        elif kind == 'MEDICAL_REPORT' and path.startswith('report_summary.findings['):
            linked = items.get(target.get('result_item_id'))
            can_confirm = linked is not None and present(linked.get('result_raw')) and present(target.get('result_raw'))
        evidence = _semantic(target) if path != 'task' else dict(
            fields=_semantic(fields), items=_semantic(result.get('items', [])),
            summary=_semantic(result.get('report_summary', {})),
            members=[_semantic(m['fields'] if isinstance(m.get('fields'), list) else
                              [v for v in m.values() if isinstance(v, dict) and 'key' in v]) for m in result.get('members', [])],
            generic=_semantic(result.get('reviewed_generic', result.get('generic', {}))))
        checks = validate_field(kind, key, target.get('value'), context) if key else []
        problems = []
        warning = number_length_warning(kind, key, target.get('value')) if key else None
        if warning:
            problems.append(('NUMBER_LENGTH', 'number_length_v1', warning, None))
        for check in checks:
            explicit_unknown = check['status'] == 'UNKNOWN' and check['rule_id'] in {'id_cn_v1', 'xuexin_compat_v1'} and check['kind'] == 'FORMAT'
            if check['status'] == 'FAIL' or explicit_unknown:
                if warning and check['rule_id'] in {'id_cn_v1', 'pan_compat_v1', 'uscc_v1', 'xuexin_compat_v1'}:
                    continue
                problems.append(('CONFLICT' if check['kind'] == 'CROSS_DOCUMENT' else 'VALIDATION_FAILED',
                                 check['rule_id'], check['message'], context if check['kind'] == 'CROSS_DOCUMENT' else None))
        current_rules = {c['rule_id'] for c in checks}
        for issue in target.get('review_issues', []):
            if issue['code'] in DISPUTE_CODES and issue.get('rule_id') not in current_rules:
                # Old generated validation issues without a rule ID are replaced
                # by current checks when their field has an explicit validator.
                if issue['code'] == 'VALIDATION_FAILED' and key and checks and not issue.get('rule_id'):
                    continue
                problems.append((issue['code'], issue.get('rule_id', ''), issue['message'], None))
        for code, rule, message, siblings in problems:
            # This editorial alias keeps v1 IDs (including legacy task issues) stable.
            identity_message = ID_CHECKSUM_LEGACY_MESSAGE if (code == 'VALIDATION_FAILED' and
                rule in (None, '', 'id_cn_v1') and message == ID_CHECKSUM_FAILURE_MESSAGE) else message
            display_message = ID_CHECKSUM_FAILURE_MESSAGE if (code == 'VALIDATION_FAILED' and
                rule in (None, '', 'id_cn_v1') and message == ID_CHECKSUM_LEGACY_MESSAGE) else message
            binding = [1, result.get('run_id'), kind, path, code, rule, identity_message, evidence, siblings]
            identifier = 'd_' + hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if not include_confirmed and can_confirm and identifier in confirmed:
                continue
            output.append(dict(dispute_id=identifier, field=path, label=label, code=code, message=display_message,
                               can_confirm=can_confirm))
    return output


def retain_confirmations(result):
    current = {d['dispute_id'] for d in export_disputes(result, include_confirmed=True) if d['can_confirm']}
    result['_export_confirmations'] = [c for c in result.get('_export_confirmations', []) if c['dispute_id'] in current]


def confirm_disputes(original, identifiers, actor):
    from copy import deepcopy
    from .task_store import TaskError, now
    current = {d['dispute_id']: d for d in export_disputes(original)}
    if (not isinstance(identifiers, list) or not identifiers or len(identifiers) > 10000 or
            any(not isinstance(i, str) or i not in current or not current[i]['can_confirm'] for i in identifiers) or
            len(set(identifiers)) != len(identifiers)):
        raise TaskError('INVALID_REQUEST', '异议已变化或尚无明确值，请先修正并读取当前结果', 422)
    result = deepcopy(original)
    retain_confirmations(result)
    result.setdefault('_export_confirmations', []).extend(
        dict(dispute_id=i, actor=actor, confirmed_at=now()) for i in identifiers)
    return result
