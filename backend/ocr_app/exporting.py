"""Snapshot-only XLSX serialization; untrusted strings never become formulas."""
from io import BytesIO
from math import ceil

from .task_store import TaskError, public_result


def _field_values(result):
    values = {key: value.get('value') if isinstance(value, dict) else value
              for key, value in result.get('basic_info', {}).items()}
    values.update({field['key']: field.get('value') for field in result.get('fields', [])})
    return values


def _generic(result):
    return result.get('reviewed_generic') if 'reviewed_generic' in result else result.get('generic')


def _missing(value):
    return value is None or isinstance(value, str) and not value.strip()


def required_export_blockers(result, required_overrides=None):
    """Check only required value presence in a saved, unfiltered result."""
    from .doc_profiles import profile, member_profile, generic_required, SUPPORTED
    if not result:
        return [dict(field='task', code='MISSING')]
    kind = result.get('doc_type')
    if kind not in SUPPORTED:
        return [dict(field='doc_type', code='MISSING')]
    values = _field_values(result)
    context = {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}
    missing = [field['key'] for field in profile(kind, context, required_overrides)
               if field['required'] and _missing(values.get(field['key']))]
    if kind == 'HOUSEHOLD_REGISTER':
        members = result.get('members') or [{}]
        for index, member in enumerate(members):
            fields = member.get('fields') if isinstance(member.get('fields'), list) else [
                value for value in member.values() if isinstance(value, dict) and 'key' in value]
            member_values = {field['key']: field.get('value') for field in fields}
            missing.extend(f'members[{index}].{field["key"]}' for field in member_profile(required_overrides)
                           if field['required'] and _missing(member_values.get(field['key'])))
    if kind == 'GENERIC' and generic_required(required_overrides) and _missing((_generic(result) or {}).get('full_text')):
        missing.append('generic.full_text')
    return [dict(field=key, code='MISSING') for key in missing]


def workbook_bytes(results):
    from openpyxl import Workbook
    from openpyxl.cell.cell import Cell
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from .doc_profiles import profile, MEMBER_PROFILE, LABELS
    from .medical_ledger import HEADERS, LEDGER_KEYS, abnormal_cell
    book = Workbook()
    book.remove(book.active)
    sheets = {}

    def sheet_for(name, headers):
        if name not in sheets:
            sheet = sheets[name] = book.create_sheet(name[:31])
            sheet.append(headers)
        return sheets[name]

    def append(name, headers, values):
        sheet = sheet_for(name, headers)
        row = []
        for value in values:
            if isinstance(value, str) and len(value) > 32767:
                raise TaskError('EXPORT_VALUE_TOO_LONG', '某结构化字段超过Excel单元格容量，请先拆分或修正字段', 422)
            cell = Cell(sheet, value=value if value is None or isinstance(value, (str, int, float, bool)) else str(value))
            if isinstance(value, str):
                cell.data_type = 's'
                cell.number_format = '@'
            row.append(cell)
        sheet.append(row)

    def field_values(result, fields):
        values = _field_values(result)
        entries = dict(result.get('basic_info', {}))
        entries.update({f['key']: f for f in result.get('fields', [])})
        row = []
        for field in fields:
            key = field['key']
            value = values.get(key)
            entry = entries.get(key, {})
            if value is None and isinstance(entry, dict):
                value = {'NOT_ON_DOCUMENT': '未载明', 'NOT_APPLICABLE': '不适用'}.get(entry.get('absence_reason'))
                if result['doc_type'] == 'MEDICAL_REPORT' and entry.get('absence_reason') == 'NOT_ON_DOCUMENT':
                    value = '报告未载明'
            if key == 'gender':
                value = {'M': '男', 'F': '女'}.get(value, value)
            row.append(value)
        return row

    medical_sequence = 0
    for result in results:
        values = _field_values(result)
        kind = result['doc_type']
        filename = result.get('_source_filename')
        fields = profile(kind)
        if kind == 'MEDICAL_REPORT':
            medical_sequence += 1
            current = public_result(result)
            definitions = {f['key']:f for f in fields}
            append('审核记录台账', HEADERS, [medical_sequence] + field_values(current,[definitions[key] for key in LEDGER_KEYS]) + [abnormal_cell(current)])
        elif kind != 'GENERIC':
            append(LABELS[kind], ['来源文件'] + [f['label'] for f in fields], [filename] + field_values(result, fields))
        for index, member in enumerate(result.get('members', [])):
            fields = member.get('fields', []) if isinstance(member.get('fields'), list) else [v for v in member.values() if isinstance(v, dict) and 'key' in v]
            field_map = {field['key']: field for field in fields}
            append('户口成员', ['来源文件', '成员序号'] + [f['label'] for f in MEMBER_PROFILE],
                   [filename, index + 1] + [field_map.get(f['key'], {}).get('value') for f in MEMBER_PROFILE])
        if kind == 'GENERIC' and _generic(result):
            generic = _generic(result)
            value = generic.get('full_text') or ''
            for index in range(0, max(1, len(value)), 500):
                append('通用识别文本', ['来源文件', '分段序号', '文本'], [filename, index // 500 + 1, value[index:index + 500]])
            for pair in generic.get('key_values', []):
                append('通用识别字段', ['来源文件', '字段', '内容'], [filename, pair['key'], pair.get('value')])
    for sheet in sheets.values():
        medical = sheet.title == '审核记录台账'
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        sheet.print_title_rows = '1:1'
        sheet.print_options.horizontalCentered = True
        widths = []
        for index, cell in enumerate(sheet[1], 1):
            width = (64 if cell.value == '文本' else 55 if cell.value in {'体检项目', '经营范围'} else
                     42 if cell.value in {'异常诊断', '检测结果', '内容'} else
                     34 if cell.value in {'来源文件', '学校名称', '名称', '住址', '住所'} else
                     27 if any(term in cell.value for term in ('编号', '号码', '卡号', '代码', '验证码', '异常项目')) else 18)
            if medical:
                width = [8,12,8,8,14,30,14,12,12,20,40,48,40,40,48,40,18,90][index-1]
            sheet.column_dimensions[get_column_letter(index)].width = width
            widths.append(width)
        for index, row in enumerate(sheet, 1):
            lines = 1
            for column, (cell, width) in enumerate(zip(row, widths),1):
                cell.alignment = Alignment(vertical='center' if medical else 'top', wrap_text=True,
                    horizontal='center' if index==1 or medical and column<11 else 'left')
                cell.font = Font(name='Microsoft YaHei', size=11, bold=index == 1, color='FFFFFF' if index == 1 else '243746')
                color = ('FF6C0D' if 11<=column<=16 else '4472C4') if medical else 'EF760E'
                cell.fill = PatternFill('solid', fgColor=color if index == 1 else 'EEF4F8' if index % 2 == 0 else 'FFFFFF')
                # Estimate visual line width, accounting for wide Chinese glyphs.
                text_lines = str(cell.value or '').split('\n')
                visual = sum(max(1, ceil(sum(2 if ord(c) > 255 else 1 for c in line) / max(1, width - 2))) for line in text_lines)
                lines = max(lines, visual)
            sheet.row_dimensions[index].height = min(409, max(30, 17 * lines + 8))
    target = BytesIO()
    book.save(target)
    return target.getvalue()


def export_results(store, request, actor, role, *, user=None):
    from sqlalchemy import text
    from .review import optional_reason, invalid
    if not isinstance(request, dict) or set(request) - {'batch_id', 'task_ids', 'versions', 'masked', 'reason', 'format'}:
        invalid()
    if bool(request.get('batch_id')) == bool(request.get('task_ids')) or request.get('format', 'xlsx') != 'xlsx':
        invalid('请选择一个批次或明确的任务列表，当前导出格式为xlsx')
    is_masked = request.get('masked', True)
    if type(is_masked) is not bool:
        invalid()
    if role not in {'operator', 'admin'}:
        raise TaskError('FORBIDDEN_REVEAL', '当前账号无完整导出权限', 403)
    optional_reason(request.get('reason'))
    snapshots = []
    with store.transaction() as connection:
        policy = store.required_policy(connection)
        if request.get('batch_id'):
            store._batch_row(connection, request['batch_id'], user)
            rows = connection.execute(text('SELECT * FROM tasks WHERE batch_id=:id ORDER BY created_at,id'), {'id': request['batch_id']}).mappings().all()
        else:
            ids = request['task_ids']
            if not isinstance(ids, list) or not ids or len(ids) > 1000 or len(set(ids)) != len(ids):
                invalid()
            rows = [store._row(connection, identifier, user) for identifier in ids]
        if not rows:
            invalid('导出选择为空')
        versions = request.get('versions')
        if versions is not None:
            if not isinstance(versions, list) or any(not isinstance(v, dict) or set(v) != {'task_id', 'run_id', 'result_revision'} for v in versions):
                invalid()
            version_map = {v['task_id']: v for v in versions}
            if len(version_map) != len(versions) or set(version_map) != {row['id'] for row in rows}:
                invalid('版本列表必须覆盖全部所选任务')
        blocked = []
        for row in rows:
            if versions is not None:
                version = version_map[row['id']]
                store._expected(row, version['run_id'], version['result_revision'])
            result = store.storage.unpack(row['result_enc'])
            problems = required_export_blockers(result, policy['overrides'])
            if problems:
                blocked.append(dict(task_id=row['id'], status=row['status'], blockers=problems))
                continue
            result.update(task_id=row['id'], run_id=row['run_id'], result_revision=row['revision'], status=row['status'])
            snapshot = public_result(result, policy['overrides'])
            snapshot['_source_filename'] = store.storage.unpack(row['meta_enc']).get('file_name')
            snapshots.append(snapshot)
        if blocked:
            raise TaskError('EXPORT_BLOCKED', '所选任务仍缺必填值，未导出任何任务', 409, {'tasks': blocked})
        for row in rows:
            store._audit(connection, 'export_full', actor, row,
                         required_fields_revision=policy['revision'],
                         result_revision=row['revision'], legacy_masked=is_masked)
            store._access_history(connection, row, actor, 'export_full', request.get('reason'), legacy_masked=is_masked)
    return workbook_bytes(snapshots)
