"""Small diagnostic helpers; production extraction remains unchanged."""
import datetime
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = {'DIPLOMA': ('### 6.4 ', '### 6.5 '),
            'DEGREE_CERT': ('### 6.5 ', '### 6.6 '),
            'MEDICAL_REPORT': ('#### 6.8.1 ', '#### 6.8.2 ')}


def templates(spec=None):
    text = (spec or ROOT / 'SPEC.md').read_text(encoding='utf-8')
    result = {}
    for kind, (start, end) in SECTIONS.items():
        section = text.split(start, 1)[1].split(end, 1)[0]
        fields = []
        for line in section.splitlines():
            cells = [v.strip() for v in line.strip('|').split('|')]
            if len(cells) == 4 and re.fullmatch(r'`[a-z_]+`', cells[0]):
                fields.append(dict(key=cells[0].strip('`'), label=cells[1],
                                   type=cells[2], required=cells[3] == '✓'))
        if not fields:
            raise ValueError('EMPTY_TEMPLATE')
        result[kind] = fields
    return result


def output_key(field, chinese=False):
    if not chinese:
        return field['key']
    return '学位级别' if field['key'] == 'degree_category' else field['label']


def prompt(fields, chinese=False):
    example = {output_key(f, chinese): 0 if f['type'] == 'int' else '' for f in fields}
    labels = {f['key']: f['label'] for f in fields}
    return ('请按下列JSON格式输出图中信息，只输出JSON。缺失或无法确定填null，不猜测。'
            '性别用M/F，年龄用整数。日期用YYYY-MM-DD；只有年月时保留YYYY-MM，不能补日。'
            '学习结束时间、发证日期、学位授予日期分别判断，不因必填而猜日期。'
            '学历层次用专科/本科/研究生/其他，学位门类用学士/硕士/博士。'
            '学习形式无明确文字不要推断。\n字段含义：'
            + (json.dumps(labels, ensure_ascii=False) if not chinese else '按输出格式中的中文字段名抽取。学位级别与学位名称分别填写。') + '\n输出格式：'
            + json.dumps(example, ensure_ascii=False))


def parse_prediction(raw, fields, termination='eos'):
    if termination != 'eos':
        return None, 'INCOMPLETE_GENERATION'
    text = raw.strip()
    if text.startswith('```') and text.endswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text).removesuffix('```').strip()
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('DUPLICATE_KEY')
            result[key] = value
        return result
    try:
        data = json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        return None, 'INVALID_JSON'
    if not isinstance(data, dict) or set(data) != {f['key'] for f in fields}:
        return None, 'INVALID_KEYS'
    for field in fields:
        value = data[field['key']]
        if value is None or value == '':
            data[field['key']] = None
        elif field['type'] == 'int':
            if type(value) is not int or not 0 <= value <= 150:
                return None, 'INVALID_TYPE'
        elif not isinstance(value, str) or len(value) > 100:
            return None, 'INVALID_TYPE'
    return data, None


def _number(value):
    digits = dict(zip('零〇一二三四五六七八九', '00123456789'))
    if '十' in value:
        left, right = value.split('十')
        return (int(digits[left]) if left else 1) * 10 + (int(digits[right]) if right else 0)
    return int(''.join(digits.get(c, c) for c in value))


def normalize(key, value):
    if value is None or value == '':
        return None
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)))
    if key == 'institution':
        # A separate trailing branch code is not part of the visible institution name.
        text = re.sub(r'\(\d{5}\)$', '', text)
    if key == 'gender':
        return {'男': 'M', '女': 'F'}.get(text, text)
    if key.endswith('_date'):
        match = re.fullmatch(r'([\d零〇一二三四五六七八九]{4})年([\d一二三四五六七八九十]{1,3})月(?:([\d一二三四五六七八九十]{1,3})日)?', text)
        if match:
            year, month = _number(match[1]), _number(match[2])
            text = f'{year:04}-{month:02}' + (f'-{_number(match[3]):02}' if match[3] else '')
        match = re.fullmatch(r'(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?', text)
        if match:
            year, month = int(match[1]), int(match[2])
            try:
                datetime.date(year, month, int(match[3]) if match[3] else 1)
            except ValueError:
                return 'INVALID_DATE:' + text
            return f'{year:04}-{month:02}' + (f'-{int(match[3]):02}' if match[3] else '')
    if key == 'duration':
        match = re.fullmatch(r'([\d一二三四五六七八九十]+)年(?:制)?', text)
        if match:
            return str(_number(match[1])) + '年'
    if key == 'degree_name':
        return text.removesuffix('学位')
    return text


def score(reference, values, fields):
    """Unknown references stay out; known absences have a separate denominator."""
    rows = []
    for field in fields:
        key = field['key']
        ref = reference[key]
        actual = normalize(key, (values or {}).get(key))
        if ref['status'] == 'uncertain':
            outcome = 'unscored'
        elif ref['status'] == 'absent':
            outcome = 'false_positive' if actual is not None else 'correct_absence'
        elif actual is None:
            outcome = 'missing'
        else:
            outcome = 'correct' if actual == normalize(key, ref['value']) else 'wrong'
        rows.append(dict(field=key, required=field['required'], reference_status=ref['status'], outcome=outcome))
    return rows
