"""Human revisions are independent of immutable recognition evidence."""
from copy import deepcopy
import re
import math
from uuid import uuid4

from .extraction import issue, confirmed_abnormal, medical_exclusion_reason, medical_statistics, _medical_item
from .task_store import TaskError
from .doc_profiles import BANK_CARD_TYPES

ABSENCE = {'NOT_ON_DOCUMENT', 'NOT_APPLICABLE'}
ITEM_KEYS = {'name', 'alias', 'category', 'result_raw', 'unit', 'reference_range',
             'reported_abnormal_marker', 'risk_grade', 'diagnosis'}
REQUEST_KEYS = {'run_id', 'expected_revision', 'fields', 'absence_reasons', 'accepted_issues',
                'items', 'added_items', 'removed_item_ids', 'findings', 'members', 'added_members', 'removed_member_indexes',
                'coverage', 'generic', 'note', 'report_summary', 'tables', 'confirmed_disputes', 'confirm_export_disputes'}


def invalid(message='复核参数无效，请检查字段和项目对应关系'):
    raise TaskError('INVALID_REQUEST', message, 422)


def reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        invalid('请填写非空核对理由')
    clean_value(value)
    return value.strip()


def optional_reason(value):
    if value is not None:
        if not isinstance(value, str) or len(value) > 1000:
            invalid('说明须为不超过1000字符的文本')
        clean_value(value)
    return value


def clean_value(value, max_length=20000):
    if value is not None and not isinstance(value, (str, int, float, bool)):
        invalid()
    if isinstance(value, float) and not math.isfinite(value):
        invalid()
    if isinstance(value, str):
        if len(value) > max_length or re.search(r'\*{2,}|[●•]{3,}|(?:\b(?:CVV2?|CVC2?|CVN2|CID)|安全码)\s*[:：]?\s*[0-9]{3,4}\b', value, re.I):
            invalid('不能提交掩码值或卡片安全码')
    return value


def mapping(value):
    if not isinstance(value, dict):
        invalid()
    return value


def sequence(value):
    if not isinstance(value, list) or len(value) > 10000:
        invalid()
    return value


def _mark(target, actor):
    target.update(reviewed=True, reviewed_by=actor, value_origin='manual', confidence=None,
                  confidence_method='unavailable')


def _sync(target):
    target['need_review'] = bool(target.get('review_issues')) and not bool(target.get('abnormal_exclusion_reason'))
    if 'review_reason' in target:
        target['review_reason'] = target['review_issues'][0]['code'] if target['review_issues'] else None


def _field_patch(result, patches, absences, actor, definitions_override=None, required_overrides=None):
    from .doc_profiles import profile
    from .validation import validate_field
    fields = {entry['key']: entry for entry in result.get('fields', [])}
    patches = dict(patches)
    if isinstance(patches.get('gender'), str):
        patches['gender'] = {'男': 'M', '女': 'F'}.get(patches['gender'].strip(), patches['gender'])
    # An unchanged value is not a correction or an implicit acceptance.
    patches = {key: value for key, value in patches.items() if key not in fields or value != fields[key].get('value')}
    values = {key: entry.get('value') for key, entry in fields.items()}
    values.update(patches)
    values.update({key: None for key in absences})
    if isinstance(values.get('gender'), str):
        values['gender'] = {'男': 'M', '女': 'F'}.get(values['gender'], values['gender'])
    definitions = {entry['key']: entry for entry in (definitions_override if definitions_override is not None else profile(result['doc_type'], values, required_overrides))}
    if (set(patches) | set(absences)) - definitions.keys() or set(patches) & set(absences):
        invalid('字段不属于当前材料类型，或同时填写值与缺省理由')
    for key, meta in definitions.items():
        target = fields.setdefault(key, dict(key=key, label=meta['label'], value=None, confidence=None,
                                            confidence_method='unavailable', review_issues=[], need_review=False))
        target.update(label=meta['label'], required=bool(meta.get('required')), editable=meta.get('editable', True))
        target.setdefault('reviewed', False)
        target.setdefault('value_origin', 'recognized')
        changed = key in patches or key in absences
        if changed and not meta.get('editable', True):
            invalid('该字段不可编辑')
        if key in absences:
            if not isinstance(absences[key], str) or absences[key] not in ABSENCE or meta.get('required'):
                invalid('必填字段不能标记为未印刷或不适用')
            if isinstance(target.get('value'), str):
                target.setdefault('_sensitive_history', []).append(target['value'])
            target.update(value=None, absence_reason=absences[key])
        elif key in patches:
            value = clean_value(patches[key])
            kind = meta.get('type', 'string')
            if value is not None and (kind in {'string', 'date', 'enum'} and not isinstance(value, str)
                                      or kind == 'integer' and type(value) is not int
                                      or kind == 'number' and (type(value) not in {int, float})
                                      or kind == 'boolean' and type(value) is not bool):
                invalid('字段类型与材料字典不符')
            if isinstance(target.get('value'), str) and target['value'] != value:
                target.setdefault('_sensitive_history', []).append(target['value'])
            target['value'] = value.strip() if isinstance(value, str) else value
            target.pop('absence_reason', None)
        if changed:
            target['review_issues'] = []
            target.pop('accepted_validation_rules', None)
            target.pop('derivation', None)
            _mark(target, actor)
        if not meta.get('required'):
            target['review_issues'] = [p for p in target['review_issues'] if p['code'] != 'CONFIDENCE_UNAVAILABLE'
                                       and not (p['code'] == 'MISSING' and not target.get('value'))]
        empty = target.get('value') is None or isinstance(target.get('value'), str) and not target['value'].strip()
        if empty and meta.get('required'):
            if not any(problem['code'] == 'MISSING' for problem in target['review_issues']):
                target['review_issues'].append(issue('MISSING', '必填字段尚未填写。'))
        checks = validate_field(result['doc_type'], key, target.get('value'), fields=values)
        target['validation_checks'] = checks
        failed_rules = {c.get('rule_id') for c in checks if c.get('status') == 'FAIL'}
        target['review_issues'] = [p for p in target['review_issues'] if not p.get('rule_id') or p['rule_id'] in failed_rules or (result['doc_type'] in BANK_CARD_TYPES and p['rule_id'].startswith('bin_reference_'))]
        for check in checks:
            if check.get('status') == 'FAIL' and check.get('rule_id') not in target.get('accepted_validation_rules', []) and not any(p.get('rule_id') == check.get('rule_id') for p in target['review_issues']):
                conflict = check.get('kind') == 'CROSS_DOCUMENT'
                blocking_pan = result['doc_type'] in BANK_CARD_TYPES and key == 'card_number' and check.get('rule_id') == 'pan_compat_v1'
                problem = issue('CONFLICT' if conflict else 'VALIDATION_FAILED', '字段未通过格式或一致性校验，请核对原件。', not (conflict or blocking_pan))
                problem['rule_id'] = check.get('rule_id')
                target['review_issues'].append(problem)
        _sync(target)
    result['fields'] = [fields[key] for key in definitions]


def _member_fields(member):
    return member['fields'] if isinstance(member.get('fields'), list) else [v for v in member.values() if isinstance(v, dict) and 'key' in v]


def _absence(target, values, allowed):
    existing = dict(target.get('absence_reasons', {}))
    for key, value in mapping(values).items():
        if key not in allowed or not isinstance(value, str) or value not in ABSENCE:
            invalid('缺省理由不适用于该项目字段')
        if target.get(key) not in (None, ''):
            invalid('已有值不能同时标记缺省')
        existing[key] = value
    target['absence_reasons'] = existing


def _medical_patch(item, patch, actor):
    prior_issues = item.get('review_issues', [])
    if not (set(patch) & ITEM_KEYS or patch.get('absence_reasons')):
        invalid('请提交实际修正或使用明确的问题确认')
    if set(patch) - ITEM_KEYS - {'item_id', 'absence_reasons'}:
        invalid('不允许修改项目派生值、来源或服务端属性')
    for key in ITEM_KEYS & patch.keys():
        value = clean_value(patch[key])
        if value is not None and not isinstance(value, str):
            invalid()
        item[key] = value
        item.get('absence_reasons', {}).pop(key, None)
    if not isinstance(item.get('name'), str) or not item['name'].strip() or not isinstance(item.get('result_raw'), str):
        invalid('项目名称与检测结果须为文本')
    clean_value(item['name'] + ': ' + item['result_raw'])
    _absence(item, patch.get('absence_reasons', {}), {'risk_grade', 'diagnosis'})
    derived = _medical_item(item['name'], item['result_raw'], item.get('unit'), item.get('reference_range'),
                            item.get('reported_abnormal_marker'), item.get('alias'), {}, [],
                            risk_grade=item.get('risk_grade'), diagnosis=item.get('diagnosis'))
    for key in ('value_num', 'ref_low', 'ref_high', 'abnormal_flag', 'abnormal_basis', 'abnormal_exclusion_reason'):
        item[key] = derived[key]
    item['reported_abnormal_marker'] = derived['reported_abnormal_marker']
    item['review_issues'] = [p for p in derived['review_issues'] if p['code'] != 'CONFIDENCE_UNAVAILABLE'
                             and not (p['code'] == 'MISSING' and item.get('absence_reasons', {}).get('risk_grade') and '等级' in p['message'])]
    if not item['result_raw'].strip() or (item.get('diagnosis_sources') and not item.get('diagnosis')
                                          and not item.get('absence_reasons', {}).get('diagnosis')):
        item['review_issues'].extend(p for p in prior_issues
                                    if p['code'] in {'CONFLICT', 'MULTI_CANDIDATES', 'LOW_CONFIDENCE'}
                                    and not any(q['code'] == p['code'] and q['message'] == p['message']
                                                for q in item['review_issues']))
    if confirmed_abnormal(item) and not item.get('diagnosis') and not item.get('absence_reasons', {}).get('diagnosis'):
        item['review_issues'].append(issue('MISSING', '异常项目诊断未填写，或须明确报告未印刷。'))
    _mark(item, actor)
    _sync(item)


def _items(result, body, actor):
    items = {entry['item_id']: entry for entry in result.get('items', [])}
    patches, added, removed = (sequence(body.get(key, [])) for key in ('items', 'added_items', 'removed_item_ids'))
    ids = [mapping(p).get('item_id') for p in patches]
    if any(not isinstance(i, str) for i in ids + removed) or len(set(ids)) != len(ids) or len(set(removed)) != len(removed) or set(ids) & set(removed) or (set(ids) | set(removed)) - items.keys():
        invalid('项目ID未知、重复或同时更新和删除')
    for identifier in removed:
        del items[identifier]
    for patch in patches:
        _medical_patch(items[patch['item_id']], patch, actor)
    for patch in added:
        if 'item_id' in mapping(patch):
            invalid('新增项目ID由服务端分配')
        entry = dict(item_id=str(uuid4()), confidence=None, confidence_method='unavailable',
                     reported_abnormal_marker=None, diagnosis_sources=[])
        _medical_patch(entry, patch, actor)
        items[entry['item_id']] = entry
    result['items'] = list(items.values())
    return items


def _findings(result, patches, items, actor):
    findings = {f['finding_id']: f for f in result.get('report_summary', {}).get('findings', [])}
    seen = set()
    for patch in sequence(patches):
        identifier = mapping(patch).get('finding_id')
        if not isinstance(identifier, str) or identifier not in findings or identifier in seen or set(patch) - {'finding_id', 'text', 'risk_grade', 'diagnosis', 'result_item_id', 'absence_reasons'}:
            invalid('清单ID未知或属性不可编辑')
        seen.add(identifier)
        if not (set(patch) - {'finding_id', 'absence_reasons'} or patch.get('absence_reasons')):
            invalid('请提交清单修正或使用明确的问题确认')
        entry = findings[identifier]
        prior_issues = entry.get('review_issues', [])
        for key in {'text', 'risk_grade', 'diagnosis'} & patch.keys():
            value = clean_value(patch[key])
            if value is not None and not isinstance(value, str):
                invalid()
            entry[key] = value
            entry.get('absence_reasons', {}).pop(key, None)
        if not isinstance(entry.get('text'), str) or not entry['text'].strip():
            invalid('清单条目内容不能为空')
        if 'result_item_id' in patch:
            if patch['result_item_id'] is not None and not isinstance(patch['result_item_id'], str):
                invalid()
            target = items.get(patch['result_item_id'])
            if patch['result_item_id'] is not None and target is None:
                invalid('清单关联项目不存在')
            entry.update(result_item_id=patch['result_item_id'], result_raw=target['result_raw'] if target else None,
                         result_sources=[target['source']] if target and target.get('source') else [])
            if target:
                entry['project_name'] = target['name']
        _absence(entry, patch.get('absence_reasons', {}), {'risk_grade', 'diagnosis', 'result_raw'})
        entry['review_issues'] = [issue('MISSING', '清单字段尚未填写或说明缺省。')
                                  for key in ('risk_grade', 'diagnosis', 'result_raw')
                                  if not entry.get(key) and not entry.get('absence_reasons', {}).get(key)]
        if (not entry.get('result_item_id') or not (entry.get('result_raw') or '').strip()) and not entry.get('absence_reasons', {}).get('result_raw'):
            entry['review_issues'].extend(p for p in prior_issues
                                        if p['code'] in {'CONFLICT', 'MULTI_CANDIDATES', 'LOW_CONFIDENCE'})
        entry.update(reviewed=True, reviewed_by=actor, value_origin='manual')
        _sync(entry)
    # Keep human links consistent when an item is changed or removed.
    for entry in findings.values():
        if entry.get('result_item_id'):
            target = items.get(entry['result_item_id'])
            if target:
                entry['project_name'] = target['name']
            entry['result_raw'] = target['result_raw'] if target else None
            entry['result_sources'] = [target['source']] if target and target.get('source') else []
            if target is None and not any(p['code'] == 'MISSING' for p in entry.get('review_issues', [])):
                entry.setdefault('review_issues', []).append(issue('MISSING', '原关联项目已删除，请重新关联。'))
            _sync(entry)


def _summary(result, body, items, actor):
    summary = result.setdefault('report_summary', dict(scope='unidentified', declared_count=None, findings=[],
                                                     count_check='unverified', sources=[]))
    patch = mapping(body)
    if set(patch) - {'declared_count', 'reason', 'source_page', 'title', 'scope', 'added_findings', 'removed_finding_ids'}:
        invalid()
    reason(patch.get('reason'))
    page = patch.get('source_page')
    if type(page) is not int or page < 1 or page not in {p.get('page_index') for p in result.get('pages', [])}:
        invalid('清单修正必须指定已有证据页')
    scope = patch.get('scope', summary.get('scope', 'unidentified'))
    if scope not in {'follow_up_required', 'overall_conclusion', 'unidentified'}:
        invalid('清单作用域无效')
    if scope == 'follow_up_required' and ('declared_count' in patch or scope != summary.get('scope')):
        reason(patch.get('title'))
    if scope != 'follow_up_required' and patch.get('declared_count') is not None:
        invalid('非随访清单不能填写该标题的声明数量')
    if scope != summary.get('scope'):
        summary.setdefault('recognition_scope', summary.get('scope'))
        summary['scope'] = scope
    removed = sequence(patch.get('removed_finding_ids', []))
    existing = {f['finding_id'] for f in summary['findings']}
    if any(not isinstance(i, str) for i in removed) or len(set(removed)) != len(removed) or set(removed) - existing:
        invalid('删除清单ID无效')
    summary['findings'] = [f for f in summary['findings'] if f['finding_id'] not in removed]
    added_patches = []
    for entry in sequence(patch.get('added_findings', [])):
        if 'finding_id' in mapping(entry):
            invalid('新增清单ID由服务端分配')
        identifier = str(uuid4())
        summary['findings'].append(dict(finding_id=identifier, text='', sources=[], reported_number=None,
                                        review_issues=[], need_review=True))
        added_patches.append(dict(entry, finding_id=identifier))
    _findings(result, added_patches, items, actor)
    if 'declared_count' in patch:
        count = patch['declared_count']
        if count is not None and (type(count) is not int or not 0 <= count <= 10000):
            invalid('清单声明数量须为非负整数或null')
        summary.setdefault('recognition_declared_count', summary.get('declared_count'))
        summary['declared_count'] = count
    summary['manual_review'] = dict(source_page=page, reason=patch['reason'], reviewed_by=actor)
    if 'title' in patch:
        summary['manual_review']['title'] = reason(patch['title'])
    if scope != 'follow_up_required':
        summary.setdefault('recognition_declared_count', summary.get('declared_count'))
        summary['declared_count'] = None
    count = summary.get('declared_count')
    summary['count_check'] = 'unverified' if count is None else 'match' if count == len(summary['findings']) else 'mismatch'
    result['review_issues'] = [p for p in result.get('review_issues', [])
                              if not (p['code'] == 'CONFLICT' and ('声明数量' in p['message'] or p.get('rule_id') == 'summary_count'))]
    if summary['count_check'] == 'mismatch':
        problem = issue('CONFLICT', '报告声明数量与清单不一致，须补正。')
        problem['rule_id'] = 'summary_count'
        result['review_issues'].append(problem)


def _targets(result):
    yield 'task', result
    for field in result.get('fields', []):
        yield field['key'], field
    for item in result.get('items', []):
        if result.get('doc_type') == 'MEDICAL_REPORT' and medical_exclusion_reason(item.get('name')):
            continue
        yield item['item_id'], item
    for finding in result.get('report_summary', {}).get('findings', []):
        yield finding['finding_id'], finding
    for index, member in enumerate(result.get('members', [])):
        for field in _member_fields(member):
            yield f'member:{index}:{field["key"]}', field


def blockers(result):
    """Only stable codes/keys/IDs, never user values, belong in error responses."""
    found = []
    for key, target in _targets(result):
        for problem in target.get('review_issues', []):
            found.append(dict(field=key, code=problem['code'], issue_id=problem['issue_id']))
    return found


def apply_review(original, body, *, actor, coverage_verified=False, required_overrides=None):
    if type(body.get('confirm_export_disputes', False)) is not bool:
        invalid('人工核对标记须为布尔值')
    if body.get('confirmed_disputes'):
        if set(mapping(body)) - REQUEST_KEYS or any(value for key, value in body.items()
                if key not in {'run_id', 'expected_revision', 'confirmed_disputes'}):
            invalid('请先保存修正，再单独确认当前异议')
        from .export_disputes import confirm_disputes
        return confirm_disputes(original, body['confirmed_disputes'], actor)
    if original.get('doc_type') == 'TABLE':
        if body.get('confirm_export_disputes'):
            invalid('表格请通过表格结构与完整性校验')
        from .table_recognition import apply_table_review
        return apply_table_review(original, body, actor)
    if 'tables' in body:
        invalid('当前材料不支持表格编辑')
    if set(mapping(body)) - REQUEST_KEYS:
        invalid('复核包含未知参数')
    if required_overrides is not None:
        from .required_fields import project_requirements
        original = project_requirements(deepcopy(original), required_overrides)
    # Validate acceptance against the incoming revision before patches remove
    # resolved issues. Accepting a resolved issue is harmless, not a stale write.
    prior = {p['issue_id']: (target, p) for _, target in _targets(original) for p in target.get('review_issues', [])}
    accepted_ids = set()
    for accepted in sequence(body.get('accepted_issues', [])):
        if set(mapping(accepted)) - {'issue_id', 'reason'} or not isinstance(accepted.get('issue_id'), str):
            invalid()
        identifier = accepted['issue_id']
        optional_reason(accepted.get('reason'))
        if identifier not in prior or identifier in accepted_ids:
            invalid('问题ID不存在或重复，请刷新当前版本')
        accepted_ids.add(identifier)
        target, problem = prior[identifier]
        informational = any(c.get('status') == 'UNKNOWN' and
            (c.get('rule_id') == problem.get('rule_id') if problem.get('rule_id') else c.get('message') == problem.get('message'))
            for c in target.get('validation_checks', []))
        informational = informational or (original.get('doc_type') in BANK_CARD_TYPES and target.get('key') == 'card_number'
            and problem.get('message') == '离线匹配不验证账户或Luhn适用性，请对照原件确认卡号。')
        explicit_failure = problem['code'] == 'VALIDATION_FAILED' and not informational
        if not problem.get('can_accept') or explicit_failure or problem['code'] in {'MISSING', 'CONFLICT', 'INCOMPLETE_OUTPUT', 'MULTI_CANDIDATES', 'LOW_CONFIDENCE'}:
            invalid('此问题必须补正，不能直接确认放行')
    result = deepcopy(original)
    xuexin = result.get('xuexin_info', {})
    if result.get('doc_type') == 'XUEXIN_DIPLOMA_TABLE' and xuexin.get('report_kind', result.get('report_kind')) in {'OTHER_REPORT', 'UNKNOWN', None}:
        if not any(p['code'] == 'UNKNOWN' for p in result.get('review_issues', [])):
            result.setdefault('review_issues', []).append(issue('UNKNOWN', '报告类型尚未确认，请上传正确材料或更正类型重新识别。'))
    if xuexin.get('manual_verify_status') == 'VERIFIED_MISMATCH' and not any(p['code'] == 'CONFLICT' for p in result.get('review_issues', [])):
        result.setdefault('review_issues', []).append(issue('CONFLICT', '人工官方核验不一致，不能放行。'))
    _field_patch(result, mapping(body.get('fields', {})), mapping(body.get('absence_reasons', {})), actor,
                 required_overrides=required_overrides)
    if result['doc_type'] in BANK_CARD_TYPES:
        from .bank_bins import normalize_pan
        from .document_fields import refresh_bank_fields
        old_pan=next((f.get('value') for f in original.get('fields',[]) if f['key']=='card_number'),None)
        new_pan=next((f.get('value') for f in result['fields'] if f['key']=='card_number'),None)
        refresh_bank_fields(result,pan_changed=normalize_pan(old_pan)!=normalize_pan(new_pan))
    if result['doc_type'] != 'MEDICAL_REPORT' and any(body.get(key) for key in ('items', 'added_items', 'removed_item_ids', 'findings', 'report_summary')):
        invalid('当前材料不支持医疗项目编辑')
    if result['doc_type'] == 'MEDICAL_REPORT':
        items = _items(result, body, actor)
        _findings(result, body.get('findings', []), items, actor)
        if 'report_summary' in body:
            summary_patch = mapping(body['report_summary'])
            removed = sequence(summary_patch.get('removed_finding_ids', []))
            if any(not isinstance(i, str) for i in removed):
                invalid()
            if set(removed) & {f.get('finding_id') for f in body.get('findings', [])}:
                invalid('同一清单条目不能同时修正和删除')
            _summary(result, body['report_summary'], items, actor)
        from .medical_ledger import refresh_ledger
        refresh_ledger(result)
    if any(body.get(k) for k in ('members', 'added_members', 'removed_member_indexes')) and result['doc_type'] != 'HOUSEHOLD_REGISTER':
        invalid()
    if result['doc_type'] == 'HOUSEHOLD_REGISTER':
        from .doc_profiles import member_profile
        member_definitions = member_profile(required_overrides)
        members = result.get('members', [])
        removed = sequence(body.get('removed_member_indexes', []))
        if any(type(i) is not int or not 0 <= i < len(members) for i in removed) or len(set(removed)) != len(removed):
            invalid('删除成员索引无效')
        seen = set()
        patch_map = {}
        for patch in sequence(body.get('members', [])):
            index = mapping(patch).get('index')
            if type(index) is not int or not 0 <= index < len(members) or index in seen or index in removed or set(patch) - {'index', 'fields', 'absence_reasons'}:
                invalid('成员索引无效或重复')
            seen.add(index)
            patch_map[index] = patch
        for index, member in enumerate(members):
            patch = patch_map.get(index, {})
            temporary = dict(doc_type='HOUSEHOLD_REGISTER', fields=_member_fields(member))
            _field_patch(temporary, mapping(patch.get('fields', {})), mapping(patch.get('absence_reasons', {})), actor, member_definitions)
            if isinstance(member.get('fields'), list):
                member['fields'] = temporary['fields']
            else:
                member.update({f['key']: f for f in temporary['fields']})
        result['members'] = [member for index, member in enumerate(members) if index not in removed]
        for patch in sequence(body.get('added_members', [])):
            if set(mapping(patch)) - {'fields', 'absence_reasons', 'source_page'}:
                invalid('新增成员ID由服务端分配')
            page = patch.get('source_page')
            if type(page) is not int or page not in {p['page_index'] for p in result.get('pages', [])}:
                invalid('新增成员须指定本文件原件页')
            temporary = dict(doc_type='HOUSEHOLD_REGISTER', fields=[])
            _field_patch(temporary, mapping(patch.get('fields', {})), mapping(patch.get('absence_reasons', {})), actor, member_definitions)
            result['members'].append(dict({f['key']: f for f in temporary['fields']}, member_id=str(uuid4()), source_page=page))
        result['review_issues'] = [p for p in result.get('review_issues', []) if p.get('rule_id') != 'household_members'
                                  and not (result['members'] and p['code'] == 'MISSING' and p.get('message') == '未确认常住人口登记卡页面，需核对材料完整性。')]
        if not result['members']:
            problem = issue('MISSING', '户口本成员尚未识别或补录，不能将扉页当完整结果。')
            problem['rule_id'] = 'household_members'
            result['review_issues'].append(problem)
        if not result.get('coverage_review') and 'coverage' not in body and not any(p['code'] == 'INCOMPLETE_OUTPUT' for p in result.get('review_issues', [])):
            result['review_issues'].append(issue('INCOMPLETE_OUTPUT', '须逐页核对户口本扉页及全部成员页。'))
    if 'generic' in body:
        if result['doc_type'] != 'GENERIC':
            invalid()
        generic = mapping(body['generic'])
        from .doc_profiles import generic_required
        if (set(generic) != {'full_text', 'key_values'} or not isinstance(generic['full_text'], str)
                or generic_required(required_overrides) and not generic['full_text'].strip()):
            invalid('通用材料须填写并核对正文')
        clean_value(generic['full_text'], max_length=1000000)
        pair_ids={p['pair_id'] for p in result.get('generic',{}).get('key_values',[]) if p.get('pair_id')}
        for pair in sequence(generic['key_values']):
            if (not {'key','value'} <= set(mapping(pair)) or set(pair)-{'key','value','source_pair_id'}
                    or not isinstance(pair['key'], str) or not pair['key'].strip()):
                invalid()
            if 'source_pair_id' in pair and (not isinstance(pair['source_pair_id'],str) or pair['source_pair_id'] not in pair_ids):
                invalid('通用字段来源不属于当前识别版本')
            clean_value(pair['key']); clean_value(pair['value'])
            if re.search(r'CVV|CVC|CVN2|安全码', pair['key'], re.I):
                invalid('通用字段不得保存卡片安全码')
        result['reviewed_generic'] = deepcopy(generic)
        result['review_issues'] = [p for p in result.get('review_issues', []) if p['code'] not in {'UNKNOWN', 'CONFIDENCE_UNAVAILABLE', 'MISSING'}]
    if 'coverage' in body:
        if not coverage_verified:
            invalid('全页证据尚未核对完成')
        result['coverage_review'] = deepcopy(body['coverage'])
        result['review_issues'] = [p for p in result.get('review_issues', []) if p['code'] != 'INCOMPLETE_OUTPUT']
    indexed = {p['issue_id']: (target, p) for _, target in _targets(result) for p in target.get('review_issues', [])}
    for accepted in sequence(body.get('accepted_issues', [])):
        identifier = accepted['issue_id']
        if identifier not in indexed:
            continue
        target, problem = indexed[identifier]
        optional_reason(accepted.get('reason'))
        if not problem.get('can_accept') or problem['code'] in {'MISSING', 'CONFLICT', 'INCOMPLETE_OUTPUT', 'MULTI_CANDIDATES'}:
            invalid('此问题必须补正，不能直接确认放行')
        target['review_issues'].remove(problem)
        if problem.get('rule_id'):
            target.setdefault('accepted_validation_rules', []).append(problem['rule_id'])
        target.update(reviewed=True, reviewed_by=actor)
        _sync(target)
        if target is result and result.get('doc_type') == 'GENERIC' and not result.get('reviewed_generic'):
            generic = result.get('generic', {})
            if isinstance(generic.get('full_text'), str) and generic['full_text'].strip():
                result['reviewed_generic'] = dict(full_text=generic['full_text'], key_values=[
                    dict(key=p['key'], value=p.get('value'),**({'source_pair_id':p['pair_id']} if p.get('pair_id') else {})) for p in generic.get('key_values', [])])
    if result.get('doc_type') == 'GENERIC' and not result.get('reviewed_generic'):
        if not any(p['code'] in {'MISSING', 'CONFIDENCE_UNAVAILABLE'} for p in result.get('review_issues', [])):
            result.setdefault('review_issues', []).append(issue('MISSING', '请完整填写或确认通用材料正文。'))
    if result['doc_type'] == 'MEDICAL_REPORT':
        items = result['items']
        for item in items:
            exclusion = medical_exclusion_reason(item.get('name'))
            if exclusion or 'abnormal_exclusion_reason' in item:
                item['abnormal_exclusion_reason'] = exclusion
            if exclusion:
                item['need_review'] = False
        result['abnormal_summary'] = [item for item in items if confirmed_abnormal(item)]
        if result.get('coverage_review') and not any(p['code'] == 'INCOMPLETE_OUTPUT' for p in result.get('review_issues', [])):
            result['stats'] = medical_statistics(items)
    if required_overrides is not None:
        project_requirements(result, required_overrides)
    from .export_disputes import retain_confirmations, export_disputes, confirm_disputes
    retain_confirmations(result)
    if body.get('confirm_export_disputes'):
        # Save acknowledges the resulting values, after edits and validation.
        identifiers = [d['dispute_id'] for d in export_disputes(result) if d['can_confirm']]
        if identifiers:
            result = confirm_disputes(result, identifiers, actor)
    result['status'] = 'NEED_REVIEW' if blockers(result) else 'COMPLETED'
    result['state'] = result['status']
    return result
