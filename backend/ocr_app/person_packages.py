"""Name suggestions reuse saved fields; they never establish identity."""
import unicodedata

NAME_FIELDS = {
    'ID_CARD_FRONT': 'name', 'DIPLOMA': 'name', 'DEGREE_CERT': 'name',
    'XUEXIN_DIPLOMA_TABLE': 'name', 'MEDICAL_REPORT': 'name',
    'PASSPORT': 'name', 'BANK_CARD': 'holder_name', 'BANK_CARD_COPY': 'holder_name', 'INTERVIEW_FORM': 'name',
}


def name_suggestions(results):
    grouped = {}
    for result in sorted(results, key=lambda r: (list(NAME_FIELDS).index(r['doc_type'])
                         if r.get('doc_type') in NAME_FIELDS else len(NAME_FIELDS), r.get('task_id', ''))):
        key = NAME_FIELDS.get(result.get('doc_type'))
        if key is None:
            continue
        fields = dict(result.get('basic_info', {}))
        fields.update({f['key']: f for f in result.get('fields', [])})
        value = fields.get(key, {}).get('value')
        if not isinstance(value, str):
            continue
        name = ' '.join(unicodedata.normalize('NFKC', value).split())
        if not 1 <= len(name) <= 80 or not name.isprintable() or name in {'未识别', '未载明', '不适用'}:
            continue
        candidate = grouped.setdefault(name, dict(name=name, sources=[]))
        candidate['sources'].append(dict(task_id=result['task_id'], doc_type=result['doc_type'],
                                         file_name=result.get('_source_filename') or '未提供文件名'))
    return list(grouped.values())
