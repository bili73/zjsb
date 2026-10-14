"""Evidence-bound field extraction; probabilities and missing values are never invented."""
from __future__ import annotations

import re
import math
from uuid import uuid4

from bs4 import BeautifulSoup
from .table_format import table_html
from .doc_profiles import profile as doc_profile

COMMON = {
    'name': ('姓名', ('姓名', '学生姓名', '学生')),
    'gender': ('性别', ('性别',)),
    'birth_date': ('出生日期', ('出生日期', '出生年月')),
    'school_name': ('学校名称', ('学校名称', '毕业院校', '授予单位', '校（院）名', '校(院)名', '校名', '学校')),
    'major': ('专业', ('专业名称', '专业')),
    'study_mode': ('学习形式', ('学习形式',)),
    'certificate_no': ('证书编号', ('学位证书编号', '毕业证书编号', '证书编号', '证书号码')),
}
DIPLOMA = {**{key: value for key, value in COMMON.items() if key != 'study_mode'}, 'education_level': ('学历层次', ('学历层次', '层次', '学历')),
           'certificate_no': (COMMON['certificate_no'][0], (*COMMON['certificate_no'][1], '书编号', '编号')),
           'duration': ('学制', ('学制',)), 'enroll_date': ('入学日期', ('入学日期', '入学时间')),
           'graduate_date': ('毕业日期', ('毕业日期', '毕业时间')), 'issue_date': ('发证日期', ('发证日期',))}
DEGREE = {**COMMON, 'degree_category': ('学位级别', ('学位级别', '学位门类', '学位类别')),
          'degree_name': ('学位名称', ('学位名称',)), 'award_date': ('学位授予日期', ('学位授予日期', '授予日期'))}
MEDICAL_ALIASES = {'name': COMMON['name'][1], 'gender': COMMON['gender'][1], 'age': ('年龄',),
                  'exam_date': ('体检日期', '检查日期', '采样日期'),
                  'institution': ('体检机构', '检查机构', '医院名称'),
                  'report_date': ('报告日期', '报告时间', '报告生成日期', '出具日期')}
MEDICAL = {f['key']:(f['label'],MEDICAL_ALIASES.get(f['key'],())) for f in doc_profile('MEDICAL_REPORT')}
PERSONAL_KEYS = {'name', 'gender', 'age', 'exam_date'}
MEDICAL_RETIRED_LABELS = ('体检编号', '体检号', '报告编号', '条码号', '体检机构', '检查机构',
                          '医院名称', '报告日期', '报告时间', '套餐名称', '婚姻状况', '婚姻',
                          '手机号码', '手机号', '手机', '联系电话', '电话', '工作单位', '单位名称')
REQUIRED = {
    'DIPLOMA': {'name', 'school_name', 'major', 'education_level', 'graduate_date', 'certificate_no'},
    'DEGREE_CERT': {'name', 'school_name', 'major', 'degree_category', 'certificate_no', 'award_date'},
    'MEDICAL_REPORT': {'name', 'gender', 'exam_date'},
}


def issue(code, message, can_accept=False):
    return dict(issue_id=str(uuid4()), code=code, message=message, can_accept=can_accept)


def source(evidence, raw_text):
    return {**{key: evidence[key] for key in ('page', 'region_id', 'extraction_method', 'bbox', 'bbox_kind') if key in evidence},
            'raw_text': raw_text}


def plain(text):
    return BeautifulSoup(text, 'html.parser').get_text(' ', strip=True) if '<' in text and '>' in text else text


def _field(key, label, candidates, required):
    unique = {}
    for value, evidence, raw in candidates:
        unique.setdefault(str(value), (value, evidence, raw))
    issues = []
    if not unique and required:
        issues.append(issue('MISSING', '必填字段未可靠提取。'))
    elif len(unique) > 1:
        issues.append(issue('CONFLICT', '来源中存在不同候选值，需要核对原件。'))
    elif unique and required:
        issues.append(issue('CONFIDENCE_UNAVAILABLE', '该字段无经过标定的置信度。', True))
    item = dict(key=key, label=label, value=None, confidence=None, confidence_method='unavailable',
                need_review=bool(issues), review_issues=issues, validation_checks=[])
    if issues:
        item['review_reason'] = issues[0]['code']
    if len(unique) == 1:
        value, evidence, raw = next(iter(unique.values()))
        item.update(value=value, source=source(evidence, raw))
    elif len(unique) > 1:
        item['candidates'] = [dict(value=value, confidence=None, confidence_method='unavailable')
                              for value, _, _ in unique.values()]
    return item


_CERT_DATE = r'(?:(?:[0-9Oo〇○零一二三四五六七八九]\s*){4}年\s*[0-9一二三四五六七八九十]{1,3}\s*月(?:\s*[0-9一二三四五六七八九十]{1,3}\s*日)?|[0-9]{4}-[0-9]{1,2}(?:-[0-9]{1,2})?)'
_CERT_FOOTER_DATE = rf'(?:{_CERT_DATE}|(?:[0-9Oo〇○零一二三四五六七八九]\s*){{4}}年\s*[0-9一二三四五六七八九十]{{1,3}}\s*月\s*[0-9一二三四五六七八九十]{{1,3}})'
_CERT_DATE_PADDING = r'[ \t（）()，,。]*'


def _certificate_date(raw, *, allow_missing_day_suffix=False):
    """Calendar validation preserves month precision; missing days are never supplied."""
    from datetime import date
    compact = re.sub(r'\s+', '', raw)
    digits = dict(zip('〇○零一二三四五六七八九Oo', '00012345678900'))

    def number(token):
        if '十' in token:
            left, right = token.split('十')
            return (int(digits.get(left, left)) if left else 1) * 10 + (int(digits.get(right, right)) if right else 0)
        return int(''.join(digits.get(c, c) for c in token))

    day_suffix = r'日?' if allow_missing_day_suffix else '日'
    parts = re.fullmatch(rf'(.+?)年(.+?)月(?:(.+?){day_suffix})?', compact)
    tokens = parts.groups() if parts else compact.split('-')
    try:
        year, month = number(tokens[0]), number(tokens[1])
        day = number(tokens[2]) if len(tokens) > 2 and tokens[2] else None
        date(year, month, day if day is not None else 1)
        return f'{year:04d}-{month:02d}' + (f'-{day:02d}' if day is not None else '')
    except (ValueError, IndexError):
        return None


def _certificate_text(raw):
    if '<' not in raw or '>' not in raw:
        return raw
    soup = BeautifulSoup(raw, 'html.parser')
    for row in soup.find_all('tr'):
        row.replace_with('\n' + '\t'.join(c.get_text(' ', strip=True) for c in row.find_all(['td', 'th'], recursive=False)) + '\n')
    for br in soup.find_all('br'):
        br.replace_with('\n')
    return soup.get_text('\n', strip=True)


def _certificate_value(key, raw, doc_type=None):
    value = raw.strip(' ：:|\t')
    if not value or len(value) > 100:
        return None
    if key.endswith('_date'):
        allow_missing_day = (doc_type, key) in {('DIPLOMA', 'issue_date'), ('DEGREE_CERT', 'award_date')}
        if allow_missing_day:
            value = value.strip(' \t\r\n（）()，,。')
        date_pattern = _CERT_FOOTER_DATE if allow_missing_day else _CERT_DATE
        return _certificate_date(value, allow_missing_day_suffix=allow_missing_day) if re.fullmatch(date_pattern, value) else None
    if key == 'gender':
        return {'男': 'M', '女': 'F', 'M': 'M', 'F': 'F'}.get(value)
    if key == 'certificate_no':
        token = re.match(r'[A-Za-z0-9]+(?=$|[\s，,。;；])', value)
        if not token or not re.search(r'\d', token[0]):
            return None
        remainder = value[token.end():].strip(' \t，,。;；')
        # A second digit group or mask may be part of the identifier, never its tail.
        date_pattern = rf'{_CERT_DATE_PADDING}{_CERT_FOOTER_DATE}{_CERT_DATE_PADDING}'
        known_tail = rf'(?:{date_pattern}\s*)?(?:查询(?:网址|地址|网站)?|网址)\s*[:：].*'
        if remainder and not re.fullmatch(date_pattern, remainder) and not re.fullmatch(known_tail, remainder):
            return None
        return token[0]
    if key == 'name':
        return value if re.fullmatch(r'[\u4e00-\u9fff·]{2,12}', value) else None
    if key == 'school_name':
        value = re.sub(r'[ \t]+', '', value)
        if value in {'普通高等学校', '成人高等学校', '高等学校'}:
            return None
        return value if re.fullmatch(r'[\u4e00-\u9fffA-Za-z（）()·]{2,60}(?:大学|学院|学校)', value) else None
    if key == 'major':
        value = re.sub(r'\s+', '', value)
        if not re.fullmatch(r'[\u4e00-\u9fffA-Za-z（）()·]{2,40}', value) or re.search(r'年制|学习|修完|介绍|大学|学院|学校', value):
            return None
    if key == 'degree_category' and value not in {'学士', '硕士', '博士'}:
        return None
    if key == 'degree_name' and not re.fullmatch(r'[\u4e00-\u9fff]{0,8}(?:学士|硕士|博士)', value):
        return None
    if key == 'education_level' and value not in {'本科', '专科', '研究生'}:
        return None
    if key == 'duration':
        value = re.sub(r'\s+', '', value)
    return value


def _extract_certificate_fields(evidence, doc_type):
    dictionary = DIPLOMA if doc_type == 'DIPLOMA' else DEGREE
    candidates = {key: [] for key in dictionary}
    schools = []
    def label_pattern(alias):
        return r'[ \t]*'.join(re.escape(c) for c in alias)

    signing_titles = ('校长', '校长姓名', '校（院）长', '校(院)长', '院长', '学位评定委员会主席')
    boundaries = {a for _, aliases in dictionary.values() for a in aliases} | set(signing_titles)
    if doc_type == 'DIPLOMA':
        boundaries.update(COMMON['study_mode'][1])
    boundary = '|'.join(label_pattern(a) for a in sorted(boundaries, key=len, reverse=True))
    compact_gender = r'性[ \t]*别[ \t]*[:：]?[ \t]*([男女MF])(?=[ \t\r\n，,。;；]|$)'
    school_token = r'[\u4e00-\u9fff][\u4e00-\u9fff \t]{1,58}?(?:大[ \t]*学|学[ \t]*院|学[ \t]*校)'
    for block in evidence:
        text = _certificate_text(block['text'])
        claimed_dates = []

        def add(key, value, raw, school_strength=2):
            if key in candidates:
                value = _certificate_value(key, value, doc_type)
                if value is not None:
                    candidates[key].append((value, block, raw))
                    if key == 'school_name':
                        schools.append((school_strength, (value, block, raw)))
                    if key == 'degree_name':
                        level = re.search(r'(学士|硕士|博士)$', value)
                        if level:
                            candidates['degree_category'].append((level[1], block, raw))

        for key, (_, aliases) in dictionary.items():
            for alias in aliases:
                endings = r'[\n\r]' if key == 'certificate_no' else r'[\n\r，,。;；\t]'
                # In spaced school names, 学 校 can overlap the beginning of 校 长.
                value_pattern = r'[\u4e00-\u9fffA-Za-z（）()· \t]{2,120}?(?:大[ \t]*学|学[ \t]*院|学[ \t]*校)' if key == 'school_name' else r'.+?'
                name_boundary = rf'|[ \t]*(?:{compact_gender})' if key == 'name' else ''
                pattern = rf'(?<![\w]){label_pattern(alias)}[ \t]*[:：\t ]+\s*({value_pattern})(?=\s*(?:{boundary})[ \t]*[:：\t ]|{endings}{name_boundary}|$)'
                for match in re.finditer(pattern, text):
                    add(key, match[1], match[0], school_strength=3)
                    if key == 'name':
                        adjacent = re.match(r'[ \t]*' + compact_gender, text[match.end():])
                        if adjacent:
                            add('gender', adjacent[1], match[0] + adjacent[0])
                    if key.endswith('_date'):
                        claimed_dates.append(match.span(1))

        # A holder identity sentence is bounded; unrelated signatories are not names.
        identity = rf'(?:^|[\n。；])\s*(?:学生\s*)?([\u4e00-\u9fff·]{{2,12}})[，,\s]+(?:性别\s*[:：]?\s*)?([男女])[，,\s]+({_CERT_DATE})\s*(?:出生|生)'
        for match in re.finditer(identity, text):
            claimed_dates.append(match.span(3))
            for key, value in zip(('name', 'gender', 'birth_date'), match.groups()):
                add(key, value, match[0])
        for match in re.finditer(r'学生\s*([\u4e00-\u9fff·]{2,12})(?=[，,\s])', text):
            add('name', match[1], match[0])
        for match in re.finditer(rf'(?:^|\n)[ \t]*({school_token})[ \t]*(?=\r?\n|$)', text):
            add('school_name', match[1], match[0], school_strength=1)
        if doc_type == 'DEGREE_CERT':
            # Signing context is as authoritative as a school label, never a fuzzy correction.
            signing = '|'.join(label_pattern(a) for a in sorted(signing_titles, key=len, reverse=True))
            for match in re.finditer(rf'(?:^|\n)[ \t]*({school_token})[ \t]*(?:\r?\n[ \t]*){{0,2}}(?:{signing})(?=[ \t:：\r\n]|$)', text):
                add('school_name', match[1], match[0], school_strength=3)
        for match in re.finditer(r'在\s*(?:本校|我校|本学院|本院|我院)\s*([\u4e00-\u9fffA-Za-z（）()\s]{2,50}?)\s*专业', text):
            add('major', match[1], match[0])
        for match in re.finditer(r'在\s*([\u4e00-\u9fff]{2,30}(?:大学|学院|学校))\s*([\u4e00-\u9fffA-Za-z（）()\s]{2,40}?)\s*专业', text):
            add('school_name', match[1], match[0])
            add('major', match[2], match[0])
        for match in re.finditer(rf'(?:于|自)\s*({_CERT_DATE})\s*(?:至|到|—|－|-)\s*({_CERT_DATE})', text):
            claimed_dates.append(match.span())
            start, end = _certificate_date(match[1]), _certificate_date(match[2])
            if start and end and start[:7] <= end[:7] and not (len(start) == len(end) == 10 and start > end):
                add('enroll_date', match[1], match[0])
                if doc_type == 'DIPLOMA':
                    add('graduate_date', match[2], match[0])
        if doc_type == 'DIPLOMA':
            for key, pattern in {
                'education_level': r'(本\s*科|专\s*科|研\s*究\s*生)\s*(?:阶段|层次|专业|学习|毕业|教\s*学\s*计\s*划)',
                'duration': r'(?<![0-9.．])((?:[0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十]+)\s*年)\s*制',
            }.items():
                for match in re.finditer(pattern, text):
                    add(key, re.sub(r'\s+', '', match[1]), match[0])
        else:
            for match in re.finditer(r'授予\s*([\u4e00-\u9fff\s]{0,12}?)(学士|硕士|博士)\s*学位', text):
                add('degree_category', match[2], match[0])
                add('degree_name', re.sub(r'\s+', '', match[1]) + match[2], match[0])
            for match in re.finditer(r'(学士|硕士|博士)\s*学位证书', text):
                add('degree_category', match[1], match[0])
        # A standalone footer date requires certificate context, not an arbitrary date.
        number_label = r'(?<!\w)(?:' + '|'.join(label_pattern(a) for a in dictionary['certificate_no'][1]) + ')'
        number_matches = list(re.finditer(rf'{number_label}\s*[:：]?\s*[A-Za-z0-9]+', text))
        if number_matches:
            footer_date = rf'{_CERT_DATE_PADDING}({_CERT_FOOTER_DATE}){_CERT_DATE_PADDING}'
            for number in number_matches:
                line_end = text.find('\n', number.end())
                tail = text[number.end():line_end if line_end >= 0 else len(text)]
                footer = re.match(rf'[ \t]+{footer_date}(?=\s*(?:$|查询|网址))', tail)
                if footer:
                    add('issue_date' if doc_type == 'DIPLOMA' else 'award_date', footer[1], number[0] + footer[0])
            for match in re.finditer(rf'(?:^|\n){footer_date}(?=\r?\n|$)', text):
                if any(start < match.end(1) and end > match.start(1) for start, end in claimed_dates):
                    continue
                add('issue_date' if doc_type == 'DIPLOMA' else 'award_date', match[1], match[0])
    if schools:
        strongest = max(strength for strength, _ in schools)
        candidates['school_name'] = [candidate for strength, candidate in schools if strength == strongest]
    fields = [_field(key, label, candidates[key], key in REQUIRED[doc_type]) for key, (label, _) in dictionary.items()]
    if doc_type == 'DEGREE_CERT' and len({value for value, _, _ in candidates['degree_category']}) > 1:
        full_name = next(f for f in fields if f['key'] == 'degree_name')
        if full_name['value'] is not None:
            full_name['candidates'] = [dict(value=full_name['value'], confidence=None, confidence_method='unavailable')]
            full_name['value'] = None
        full_name.update(need_review=True, review_reason='CONFLICT',
                         review_issues=[issue('CONFLICT', '学位级别来源不一致，完整学位名称也需核对。')])
    return fields


def _cell_evidence(block, row_index, column=None):
    rows = block.get('table_rows', [])
    row = rows[row_index] if row_index < len(rows) else {}
    cells = row.get('cell_bboxes', [])
    if column is not None and column < len(cells) and cells[column]:
        return {**block, 'bbox': cells[column], 'bbox_kind': 'cell'}
    return {**block, 'bbox': row['bbox'], 'bbox_kind': 'row'} if row.get('bbox') else block


def _personal_value(key, value):
    value = value.strip()
    if not value or len(value) > 100:
        return None
    if key == 'gender':
        return {'男': 'M', '女': 'F', 'M': 'M', 'F': 'F'}.get(value)
    if key == 'age':
        match = re.fullmatch(r'(\d{1,3})\s*岁?', value)
        return int(match[1]) if match else None
    if key == 'exam_date':
        return _certificate_date(value)
    return value


def _personal_candidates(evidence):
    """A real section and a same-page label/value table, never a contents mention."""
    aliases = {re.sub(r'\s+', '', label): key for key in PERSONAL_KEYS for label in MEDICAL[key][1]}
    title = re.compile(r'^\s*一\s*[、.．]\s*个\s*人\s*信\s*息\s*[:：]?\s*$')
    section = re.compile(r'^\s*(?:[一二三四五六七八九十]+\s*(?:[、.．:：]|\s)|\d{1,2}\s*[、.．:：])\s*[\u4e00-\u9fff]')
    title_hint = re.compile(r'(?:^|\n)\s*(?:一|1)\s*[、.．:：]?\s*个\s*人\s*信\s*息')
    candidates = {key: [] for key in PERSONAL_KEYS}
    active_page, accepted, hinted = None, False, False
    ordered = sorted(enumerate(evidence), key=lambda pair: (pair[1].get('page', 0), (pair[1].get('bbox') or [0,0])[1], pair[0]))
    for _, block in ordered:
        page = block.get('page')
        if page != active_page:
            active_page = None
        try:
            soup = BeautifulSoup(table_html(block['text']), 'html.parser')
        except ValueError:
            continue
        hinted = hinted or bool(title_hint.search(soup.get_text('\n', strip=True)))
        # Walk external text and whole tables in document order. This also handles
        # an OCR block containing both the section title and the table itself.
        for node in soup.descendants:
            if getattr(node, 'name', None) == 'table':
                if node.find_parent('table') is not None or active_page != page:
                    continue
                grid = _grid(node)
                labels = {aliases.get(re.sub(r'\s+', '', cell).strip(':：')) for row in grid for cell in row}
                if 'name' not in labels or len(labels & PERSONAL_KEYS) < 3:
                    continue
                accepted = True
                for ri, row in enumerate(grid):
                    for ci, label in enumerate(row[:-1]):
                        key = aliases.get(re.sub(r'\s+', '', label).strip(':：'))
                        if key is None or re.sub(r'\s+', '', row[ci + 1]).strip(':：') in aliases:
                            continue
                        value = _personal_value(key, row[ci + 1])
                        if value is not None:
                            candidates[key].append((value, _cell_evidence(block, ri, ci + 1), label + '：' + row[ci + 1]))
            elif getattr(node, 'name', None) is None and node.find_parent('table') is None:
                for line in str(node).splitlines():
                    if title.fullmatch(line):
                        active_page = page
                    elif section.match(line):
                        active_page = None
    # A rejected/missing section table must not re-enter through global regexes.
    # Untitled legacy reports retain their existing plain-label compatibility.
    return accepted or hinted, candidates


def extract_fields(evidence, doc_type):
    from .doc_profiles import profile
    if doc_type not in {'DIPLOMA', 'DEGREE_CERT', 'MEDICAL_REPORT'}:
        from .doc_profiles import SUPPORTED
        if doc_type in SUPPORTED:
            from .document_fields import extract_document_fields
            return extract_document_fields(evidence, doc_type)['fields']
    if doc_type in {'DIPLOMA', 'DEGREE_CERT'}:
        return _extract_certificate_fields(evidence, doc_type)
    dictionary = {'DIPLOMA': DIPLOMA, 'DEGREE_CERT': DEGREE, 'MEDICAL_REPORT': MEDICAL}.get(doc_type, {})
    labels = sorted({alias for _, aliases in dictionary.values() for alias in aliases}
                    | (set(MEDICAL_RETIRED_LABELS) if doc_type == 'MEDICAL_REPORT' else set()), key=len, reverse=True)
    boundary = '|'.join(map(re.escape, labels))
    candidates = {key: [] for key in dictionary}
    scoped, personal = _personal_candidates(evidence) if doc_type == 'MEDICAL_REPORT' else (False, {})
    for block in evidence:
        text = plain(block['text'])
        for key, (_, aliases) in dictionary.items():
            if scoped and key in PERSONAL_KEYS:
                continue
            for alias in aliases:
                # A label must have punctuation or whitespace; do not match narrative substrings.
                pattern = rf'(?<![\w]){re.escape(alias)}\s*[:：\t ]+\s*(.+?)(?=\s*(?:{boundary})\s*[:：\t ]|[\n\r;；]|$)'
                for match in re.finditer(pattern, text):
                    value = match.group(1).strip(' ：:|')
                    if not value or len(value) > 100:
                        continue
                    if key == 'age':
                        age = re.fullmatch(r'(\d{1,3})\s*岁?', value)
                        if not age:
                            continue
                        value = int(age.group(1))
                    elif key == 'gender':
                        if value not in {'男', '女', 'M', 'F'}:
                            continue
                        value = {'男': 'M', '女': 'F'}.get(value, value)
                    candidates[key].append((value, block, match.group(0)))
    if scoped:
        candidates.update(personal)
    fields = [_medical_project_field(evidence) if key == 'exam_projects' else
              _field(key, label, candidates[key], key in REQUIRED.get(doc_type, set()))
              for key, (label, _) in dictionary.items()]
    return fields


def _medical_project_field(evidence):
    return _medical_project_catalogue(evidence)[0]


def _medical_project_catalogue(evidence):
    """Read the broad project column only in the titled meaning-table section."""
    title = re.compile(r'^(?:[一二三四五六七八九十0-9]+[、.．:：])?本次体检项目意义[:：]?$')
    chapter = re.compile(r'^[一二三四五六七八九十0-9]+[、.．:：][\u4e00-\u9fff]')
    active, previous_page, names, sources = False, None, [], []
    primary, ambiguous = None, False
    numbers, closed, gap, sections = [], False, False, 0
    ordered = sorted(enumerate(evidence), key=lambda pair: (pair[1].get('page', 0), (pair[1].get('bbox') or [0,0])[1], pair[0]))
    for _, block in ordered:
        page = block.get('page')
        if previous_page is not None and page not in (previous_page, previous_page + 1):
            gap = gap or active
            active = False
        previous_page = page
        try:
            soup = BeautifulSoup(table_html(block['text']), 'html.parser')
        except ValueError:
            continue
        geometry = block if len(soup.find_all('table')) == 1 else {k:v for k,v in block.items() if k != 'table_rows'}
        for node in soup.descendants:
            if getattr(node, 'name', None) == 'table':
                if not active or node.find_parent('table') is not None:
                    continue
                column = None
                number_column = None
                for index, row in enumerate(_grid(node)):
                    headers = [re.sub(r'\s+', '', c).strip(':：') for c in row]
                    if '项目' in headers and '临床意义' in headers:
                        if headers.count('项目') != 1 or headers.count('临床意义') != 1:
                            ambiguous = True
                            column = None
                        else:
                            column = headers.index('项目')
                            number_column = headers.index('序号') if headers.count('序号') == 1 else None
                        continue
                    if column is None or column >= len(row) or not row[column].strip():
                        if column is not None and any(c.strip() for c in row):
                            numbers.append(None)
                        continue
                    raw = row[column]
                    name = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', raw).strip()
                    if name not in names:
                        names.append(name)
                    number = row[number_column].strip() if number_column is not None and number_column < len(row) else ''
                    numbers.append(int(number) if re.fullmatch(r'[0-9]+', number) else None)
                    sources.append(source(_cell_evidence(geometry, index, column), raw))
                    if primary is None:
                        primary = (block, node.get_text('\n', strip=True))
            elif getattr(node, 'name', None) is None and node.find_parent('table') is None:
                for line in str(node).splitlines():
                    compact = re.sub(r'\s+', '', line).strip('#*')
                    if title.fullmatch(compact):
                        active = True
                        sections += 1
                    elif chapter.match(compact) or compact == '检后服务介绍':
                        closed = closed or (active and bool(names))
                        active = False
    candidates = [('；'.join(names), primary[0], primary[1])] if names and not ambiguous else []
    field = _field('exam_projects', '体检项目', candidates, False)
    if sources:
        field['sources'] = sources
    if ambiguous:
        field.update(need_review=True, review_reason='CONFLICT',
                     review_issues=[issue('CONFLICT', '体检项目意义表列标题重复，未猜选项目列。')])
    complete = bool(candidates and closed and not gap and sections == 1
                    and numbers == list(range(1, len(names) + 1)))
    return field, complete


HEADER = {
    'name': {'项目', '项目名称', '检验项目', '检测项目', '检查项目', '中文名称'},
    'result': {'结果', '检测结果', '检验结果', '检查结果', '测定值'},
    'alias': {'缩写', '英文缩写', '代号', '英文名称'},
    'unit': {'单位', '结果单位'},
    'range': {'参考范围', '参考区间', '参考值', '正常范围'},
    'marker': {'提示', '标志', '标识', '异常', '异常标记'},
    'grade': {'风险等级', '等级'},
    'diagnosis': {'异常诊断', '诊断'},
}


def _grid(table):
    """Expand HTML spans so values remain in their actual result columns."""
    rows, spans = [], {}
    for tr in table.find_all('tr'):
        cells, column = {}, 0
        for col, (left, value) in list(spans.items()):
            cells[col] = value
            if left <= 1:
                del spans[col]
            else:
                spans[col] = (left - 1, value)
        for cell in tr.find_all(['th', 'td'], recursive=False):
            while column in cells:
                column += 1
            value = cell.get_text(' ', strip=True)
            try:
                colspan, rowspan = int(cell.get('colspan', 1)), int(cell.get('rowspan', 1))
            except ValueError:
                colspan = rowspan = 1
            colspan, rowspan = min(max(colspan, 1), 50), min(max(rowspan, 1), 1000)
            for offset in range(colspan):
                cells[column + offset] = value
                if rowspan > 1:
                    spans[column + offset] = (rowspan - 1, value)
            column += colspan
        rows.append([cells.get(i, '') for i in range(max(cells, default=-1) + 1)])
    return rows


ARROW_TOKEN = re.compile(r'\\(?:uparrow|downarrow)(?![A-Za-z])|[↑↓]')
LETTER_VALUE = re.compile(r'([HL])?\s*([+-]?\d+(?:\.\d+)?)\s*([HL])?')


def medical_exclusion_reason(name):
    label = re.sub(r'\s+', '', name or '').rstrip(':：')
    if label == '小结':
        return 'SECTION_SUMMARY'
    return 'HEIGHT_WEIGHT' if label in {'身高', '体重', '身高体重', '身高/体重', '身高、体重'} else None


def confirmed_abnormal(item):
    if medical_exclusion_reason(item.get('name')):
        return False
    return item.get('abnormal_flag') in {'HIGH', 'LOW', 'ABNORMAL'} or (
        item.get('abnormal_flag') == 'POSITIVE' and item.get('abnormal_basis') in {'report_marker', 'reference_comparison'})


def medical_statistics(items):
    eligible = [item for item in items if not medical_exclusion_reason(item.get('name'))]
    abnormal = sum(confirmed_abnormal(item) for item in eligible)
    normal = sum(item.get('abnormal_flag') == 'NORMAL' for item in eligible)
    return dict(total=len(eligible), normal=normal, abnormal=abnormal, unknown=len(eligible)-normal-abnormal,
                categories=sorted({item['category'] for item in eligible if item.get('category')}))


def _medical_item(name, result, unit, reference, marker, alias, block, row, *, risk_grade=None,
                  diagnosis=None, diagnosis_source=None):
    raw = result.strip()
    tokens = [m.group() for text in (marker or '', raw) for m in ARROW_TOKEN.finditer(text)]
    explicit = re.sub(r'\s+', '', marker or '')
    scalar = ARROW_TOKEN.sub('', raw).strip()
    if len(scalar) >= 2 and scalar.startswith('$') and scalar.endswith('$'):
        scalar = scalar[1:-1].strip()
    letter_value = LETTER_VALUE.fullmatch(scalar)
    if explicit in {'H', 'L'}:
        tokens.append(explicit)
    if letter_value:
        tokens.extend(token for token in (letter_value[1], letter_value[3]) if token)
        scalar = letter_value[2]
    directions = {'HIGH' if t in {'↑', 'H', r'\uparrow'} else 'LOW' for t in tokens}
    if explicit in {'偏高', '偏低'}:
        directions.add('HIGH' if explicit == '偏高' else 'LOW')
    positive = bool(re.fullmatch(r'(?:阳性(?:[（(]\+[）)])?|\+)', re.sub(r'\s+', '', raw)))
    flag, basis = 'UNKNOWN', 'unknown'
    reported = tokens[0] if tokens else (marker or ('阳性' if positive else None))
    issues = [issue('CONFIDENCE_UNAVAILABLE', '项目识别无经过标定的置信度。', True)]
    if not raw:
        issues.append(issue('MISSING', '检测结果未可靠提取，保留项目和原行供人工核对。'))
    conflicting = len(directions) > 1 or bool(directions and explicit in {'正常', '阴性', '未见异常'})
    if conflicting:
        issues.append(issue('CONFLICT', '报告结果与标记来源存在矛盾，请核对原行。'))
    elif directions:
        flag, basis = next(iter(directions)), 'report_marker'
    elif explicit in {'异常', '偏高', '偏低', '正常'}:
        flag = {'异常': 'POSITIVE' if positive else 'ABNORMAL', '偏高': 'HIGH', '偏低': 'LOW', '正常': 'NORMAL'}[explicit]
        basis = 'report_marker'
    elif positive:
        flag = 'POSITIVE'
    # Parse explicit display syntax only. Original text, precision and digits remain untouched.
    value = float(scalar) if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', scalar) else None
    if value is not None and not math.isfinite(value):
        value = None
    limits = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*[-~～—–]\s*([+-]?\d+(?:\.\d+)?)\s*', reference or '')
    low, high = (float(limits[1]), float(limits[2])) if limits else (None, None)
    if low is not None and (not math.isfinite(low) or not math.isfinite(high) or low > high):
        low = high = None
    compared = None
    if value is not None and low is not None:
        compared = 'LOW' if value < low else 'HIGH' if value > high else 'NORMAL'
    if not conflicting and flag == 'UNKNOWN' and compared is not None:
        flag, basis = compared, 'reference_comparison'
    elif not conflicting and flag in {'HIGH', 'LOW', 'NORMAL'} and compared is not None and compared != flag:
        issues.append(issue('CONFLICT', '报告标记与本行数值及参考范围不一致，请核对项目、单位和适用范围。'))
    grade = (risk_grade or '').strip() or None
    diagnosis = (diagnosis or '').strip() or None
    if grade is None:
        issues.append(issue('MISSING', '报告等级未可靠提取，不能据此判断正常。'))
    elif grade not in {'A', '/'} and flag not in {'HIGH', 'LOW', 'ABNORMAL'}:
        if flag == 'NORMAL':
            issues.append(issue('CONFLICT', '报告等级提示异常，但其他依据提示正常，请核对原行。'))
        flag, basis = 'ABNORMAL', 'report_grade'
    if diagnosis is not None and diagnosis not in {'正常', '未见异常', '无异常', '/', '-'} and flag not in {'HIGH', 'LOW', 'ABNORMAL'}:
        if flag == 'NORMAL':
            issues.append(issue('CONFLICT', '明确异常诊断与正常标记或参考区间不一致，请核对。'))
        flag, basis = 'ABNORMAL', 'report_marker'
    return dict(item_id=str(uuid4()), name=name, alias=alias or None, category=None,
                result_raw=raw, value_num=value, unit=unit or None, reference_range=reference or None,
                ref_low=low, ref_high=high, abnormal_flag=flag, reported_abnormal_marker=reported,
                abnormal_basis=basis, abnormal_exclusion_reason=medical_exclusion_reason(name),
                confidence=None, confidence_method='unavailable', need_review=not bool(medical_exclusion_reason(name)),
                review_issues=issues, risk_grade=grade, diagnosis=diagnosis,
                diagnosis_sources=[diagnosis_source or source(block, diagnosis)] if diagnosis else [],
                source=source(block, ' | '.join(row)))


def extract_medical_items(evidence):
    items, limitations = [], []
    for block in evidence:
        try:
            text = table_html(block['text'])
        except ValueError:
            limitations.append('OTSL表格结构不完整，未猜测单元格归属；原始输出保留供复核。')
            continue
        soup = BeautifulSoup(text, 'html.parser')
        for table in soup.find_all('table'):
            columns = None
            for row_index, row in enumerate(_grid(table)):
                mapped, duplicates = {}, set()
                for i, cell in enumerate(row):
                    normalized = re.sub(r'\s+', '', cell).strip(':：')
                    for key, names in HEADER.items():
                        if normalized in names:
                            if key in mapped:
                                duplicates.add(key)
                            mapped[key] = i
                if 'name' in mapped and 'result' in mapped:
                    if duplicates:
                        columns = None
                        limitations.append('表格列标题重复，无法确定单一字段归属；原文保留供复核。')
                        continue
                    columns = mapped
                    continue
                if not columns:
                    continue
                def get(key):
                    index = columns.get(key, len(row))
                    return row[index] if index < len(row) else ''
                # A subsection summary is evidence, not an individual test item.
                if re.sub(r'\s+', '', get('name')).rstrip(':：') == '小结':
                    continue
                if not get('name').strip() or not any(get(key).strip() for key in ('result', 'grade', 'diagnosis')):
                    if any(row):
                        limitations.append('表格存在无法确定项目或结果列的行，需要核对原页。')
                    continue
                geometry = block.get('table_rows', [])
                row_block = {**block, 'bbox': geometry[row_index]['bbox'], 'bbox_kind': 'row'} if (
                    row_index < len(geometry) and geometry[row_index].get('bbox')) else block
                items.append(_medical_item(get('name'), get('result'), get('unit'), get('range'),
                                           get('marker'), get('alias'), row_block, row,
                                           risk_grade=get('grade'), diagnosis=get('diagnosis'),
                                           diagnosis_source=source(_cell_evidence(block, row_index, columns.get('diagnosis')), get('diagnosis')) if get('diagnosis') else None))
            if columns is None:
                limitations.append('存在未识别列标题的表格，未猜测列的含义。')
    if not items:
        limitations.append('未获得可可靠按项目和结果列对齐的医疗表格；原文保留供复核。')
    return items, list(dict.fromkeys(limitations))


def _link_report_findings(findings, projects, items):
    """Join exact unique project names only, preserving separate source scopes."""
    def identity(value):
        return re.sub(r'\s+', '', value)
    named_items, named_findings = {}, {}
    for item in items:
        named_items.setdefault(identity(item['name']), []).append(item)
    for finding in findings:
        name = projects.get(finding['finding_id'])
        if name:
            named_findings.setdefault(identity(name), []).append(finding)
    for name, candidates in named_findings.items():
        matches = named_items.get(name, [])
        if len(candidates) > 1 and len(matches) == 1:
            item = matches[0]
            item['diagnosis'] = None
            for candidate in candidates:
                item['diagnosis_sources'].extend(s for s in candidate['sources'] if s not in item['diagnosis_sources'])
            item['review_issues'].append(issue('CONFLICT', '同一项目有多个诊断清单条目，保留全部来源但不选择诊断。'))
    for finding in findings:
        finding.setdefault('risk_grade', None)
        finding.setdefault('diagnosis', None)
        finding.update(project_name=projects.get(finding['finding_id']), result_item_id=None,
            result_raw=None, result_sources=[], need_review=True,
            review_issues=[issue('CONFIDENCE_UNAVAILABLE', '报告清单条目无经过标定的置信度。', True)])
        if finding['risk_grade'] is None:
            finding['review_issues'].append(issue('MISSING', '清单条目的报告等级未可靠提取。'))
        if finding['diagnosis'] is None:
            finding['review_issues'].append(issue('MISSING', '清单条目的诊断未可靠分离，保留原文核对。'))
        name = projects.get(finding['finding_id'])
        matches = named_items.get(identity(name), []) if name else []
        if not matches:
            finding['review_issues'].append(issue('MISSING', '未找到可唯一关联的检测结果，保留清单原文。'))
            continue
        if len(matches) != 1 or len(named_findings[identity(name)]) != 1:
            finding['review_issues'].append(issue('CONFLICT', '项目有多个候选结果或诊断，未猜测跨表对应关系。'))
            continue
        item = matches[0]
        finding['result_item_id'] = item['item_id']
        if item['result_raw']:
            finding['result_raw'] = item['result_raw']
            finding['result_sources'] = [dict(item['source'])] if item.get('source') else []
        else:
            finding['review_issues'].append(issue('MISSING', '对应项目的检测结果未可靠提取，请核对原行。'))
        grade = finding['risk_grade']
        if grade is not None and grade not in {'A', '/'}:
            if item['risk_grade'] is not None and item['risk_grade'] != grade:
                for target in (item, finding):
                    target['review_issues'].append(issue('CONFLICT', '同项目的检测表和清单等级不一致，保留各自原值及来源核对。'))
            if item['abnormal_flag'] not in {'HIGH', 'LOW'}:
                item['abnormal_flag'], item['abnormal_basis'] = 'ABNORMAL', 'report_grade'
        if finding['diagnosis']:
            if item['diagnosis'] not in (None, finding['diagnosis']):
                item['diagnosis'] = None
                item['diagnosis_sources'].extend(finding['sources'])
                for target in (item, finding):
                    target['review_issues'].append(issue('CONFLICT', '同项目的检测表和清单诊断不一致，需核对原来源。'))
            else:
                item['diagnosis'] = finding['diagnosis']
                item['diagnosis_sources'].extend(s for s in finding['sources'] if s not in item['diagnosis_sources'])
                if item['abnormal_flag'] not in {'HIGH', 'LOW', 'ABNORMAL'}:
                    if item['abnormal_flag'] == 'NORMAL':
                        item['review_issues'].append(issue('CONFLICT', '明确异常清单与检测表正常依据不一致，需核对。'))
                    item['abnormal_flag'], item['abnormal_basis'] = 'ABNORMAL', 'report_marker'
def extract_report_summary(evidence, *, complete=False, items=None):
    """Extract one evidence-bound conclusion list, never laboratory abnormal counts."""
    result = dict(scope='unidentified', declared_count=None, findings=[],
                  count_check='unverified', sources=[])
    finding_projects = {}
    ordered = sorted(enumerate(evidence), key=lambda pair: (
        pair[1].get('page', 0), (pair[1].get('bbox') or [0, 0])[1], pair[0]))
    blocks, parts, offset = [], [], 0
    tables = []
    for _, block in ordered:
        try:
            html = table_html(block['text'])
        except ValueError:
            html = block['text']
        soup = BeautifulSoup(html, 'html.parser')
        if soup.find('table'):
            found = soup.find_all('table')
            tables.append((block, found))
            # Keep external headings for scope detection, never flatten cells into prose.
            for table in found:
                table.extract()
            text = soup.get_text('\n', strip=True)
            if not text:
                continue
        else:
            text = block['text']
        blocks.append((offset, offset + len(text), block))
        parts.append(text)
        offset += len(text) + 1
    joined = '\n'.join(parts)
    endings = re.compile(r'(?:^|\n)\s*(?:总检医师|总检医生|健康建议|名词解释|异常结果解释|健康指导|温馨提示|总检结论)\s*[:：]?')
    marker = re.compile(r'(?:^|\n)[ \t]*(?:(\d{1,3})[、.．)）]|[\uf076•●▪◆])[ \t]*')
    title = re.compile(r'您\s*共\s*有\s*(\d{1,3})\s*项\s*异\s*常\s*需\s*进\s*一\s*步\s*检\s*查\s*并\s*治\s*疗\s*[:：]?')
    def position(block):
        return (block.get('page', 0), (block.get('bbox') or [0, 0])[1])
    def header_row(rows):
        for row in rows:
            labels = [re.sub(r'\s+', '', cell) for cell in row]
            if all(labels.count(label) == 1 for label in ('序号', '项目', '异常诊断')):
                return labels
        return None
    declarations = list(title.finditer(joined))
    if declarations:
        start = declarations[0]
        selected_score = 0
        for index, candidate in enumerate(declarations):
            stop = endings.search(joined, candidate.end())
            bound = min(stop.start() if stop else len(joined),
                        declarations[index + 1].start() if index + 1 < len(declarations) else len(joined))
            origin = next(block for begin, end, block in blocks if begin <= candidate.start() < end)
            boundary = next((block for begin, end, block in blocks if end > bound), None)
            has_table = any(block.get('page') == origin.get('page') and position(block) >= position(origin)
                            and (boundary is None or position(block) < position(boundary))
                            and any(header_row(_grid(table)) is not None for table in found)
                            for block, found in tables)
            score = 2 if has_table else int(bool(marker.search(joined[candidate.end():bound])))
            if score > selected_score:
                start = candidate
                selected_score = score
        counts = {int(match[1]) for match in declarations}
        result.update(scope='follow_up_required', declared_count=next(iter(counts)) if len(counts) == 1 else None)
    else:
        overall = list(re.finditer(r'总\s*检\s*结\s*论', joined))
        if not overall:
            return result
        start = overall[0]
        # A contents-page mention is not the conclusion list itself.
        for candidate in overall:
            stop = endings.search(joined, candidate.end())
            if marker.search(joined[candidate.end():stop.start() if stop else len(joined)]):
                start = candidate
                break
        result['scope'] = 'overall_conclusion'
    ending = endings.search(joined, start.end())
    finish = ending.start() if ending else len(joined)
    # Another declaration opens a new list, even when it reports the same number.
    later = next((match for match in declarations if match.start() > start.start()), None)
    if later:
        finish = min(finish, later.start())
    def sources_between(left, right):
        return [source(block, joined[max(left, begin):min(right, end)])
                for begin, end, block in blocks if begin < right and end > left]
    conflicting = [match for match in declarations if match != start] if declarations and len(counts) > 1 else []
    for match in [start] + conflicting:
        result['sources'].extend(sources_between(match.start(), match.end()))
    if ending:
        result['sources'].extend(sources_between(ending.start(), ending.end()))
    start_block = next(block for begin, end, block in blocks if begin <= start.start() < end)
    end_block = next((block for begin, end, block in blocks if end > finish), None)
    table_findings, table_complete, table_bad = [], True, False
    continuation_header, last_table_page = None, None
    if result['scope'] == 'follow_up_required':
        for block, found_tables in tables:
            if position(block) < position(start_block) or (end_block and position(block) >= position(end_block)):
                continue
            for table in found_tables:
                grid = _grid(table)
                signature = header_row(grid)
                if signature is None:
                    if any(all(label in [re.sub(r'\s+', '', cell) for cell in row]
                               for label in ('序号', '项目', '异常诊断')) for row in grid):
                        table_bad = True
                    continue
                if block.get('page') != start_block.get('page'):
                    # Adjacent native tables must repeat the exact structure and continue numbering.
                    first_number = next((int(row[signature.index('序号')]) for row in grid
                                         if signature and len(row) > signature.index('序号')
                                         and re.fullmatch(r'\d{1,3}', row[signature.index('序号')])), None)
                    if (not table_findings or block.get('extraction_method') != 'pdf_text'
                            or signature != continuation_header or block.get('page') != last_table_page + 1
                            or first_number != int(table_findings[-1]['reported_number']) + 1):
                        if signature is not None:
                            table_bad = True
                        continue
                columns = None
                seen_data = False
                for row_index, row in enumerate(grid):
                    labels = [re.sub(r'\s+', '', cell) for cell in row]
                    if all(label in labels for label in ('序号', '项目', '异常诊断')):
                        if any(labels.count(label) != 1 for label in ('序号', '项目', '异常诊断')):
                            columns, table_bad = None, True
                            continue
                        columns = {label: labels.index(label) for label in ('序号', '项目', '异常诊断')}
                        grade_columns = [i for i, label in enumerate(labels) if label in {'风险等级', '等级'}]
                        if len(grade_columns) == 1:
                            columns['grade'] = grade_columns[0]
                        continue
                    if columns is None or not any(labels):
                        continue
                    # A second header tier is not a finding.
                    if '序号' in labels:
                        continue
                    def cell(label):
                        index = columns[label]
                        return row[index].strip() if index < len(row) else ''
                    number = cell('序号')
                    if (not seen_data and not number and not cell('项目') and not cell('异常诊断')
                            and set(filter(None, labels)) <= {'复查建议', '复查项目', '就诊科室', '用药指导'}):
                        continue
                    if not re.fullmatch(r'\d{1,3}', number) or not cell('项目') or not cell('异常诊断'):
                        table_bad = True
                        continue
                    row_meta = block.get('table_rows', [])
                    box = row_meta[row_index].get('bbox') if row_index < len(row_meta) else None
                    local = {**block, **({'bbox': box} if box else {})}
                    raw = ' | '.join(row)
                    origin = source(local, raw)
                    if box:
                        origin['bbox_kind'] = 'row'
                    table_complete = table_complete and bool(box) and block.get('extraction_method') == 'pdf_text'
                    seen_data = True
                    table_findings.append(dict(finding_id=str(uuid4()), reported_number=number,
                                               text=' | '.join(row[columns['项目']:]), sources=[origin],
                                               risk_grade=cell('grade') or None if 'grade' in columns else None,
                                               diagnosis=cell('异常诊断')))
                    finding_projects[table_findings[-1]['finding_id']] = cell('项目')
                if columns is not None:
                    result['sources'].append(source(block, ''))
                if seen_data:
                    continuation_header, last_table_page = signature, block.get('page')
    native_coverage = bool(table_findings) and table_complete and not table_bad
    if table_findings:
        result['findings'] = table_findings
    else:
        body = joined[start.end():finish]
        markers = list(marker.finditer(body))
        for index, match in enumerate(markers):
            right = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            text = body[match.end():right].strip()
            if text:
                result['findings'].append(dict(finding_id=str(uuid4()), reported_number=match[1], text=text,
                    sources=sources_between(start.end() + match.start(), start.end() + right)))
    if result['scope'] == 'overall_conclusion' and not result['findings']:
        result['scope'] = 'unidentified'
    count = result['declared_count']
    if count is not None:
        numbers = [finding['reported_number'] for finding in result['findings']]
        numeric = [int(number) for number in numbers if number is not None]
        duplicate = len(set(numeric)) != len(numeric)
        consecutive = len(numeric) == len(numbers) and numeric == list(range(1, len(numbers) + 1))
        bounded = complete and ending is not None and not table_bad
        coverage = (native_coverage and consecutive and len(numbers) == count) or bounded
        contradiction = bool(numeric) and (not consecutive or max(numeric) > count)
        if duplicate or contradiction or (bounded and len(numbers) != count):
            result['count_check'] = 'mismatch'
        elif coverage and len(numbers) == count and (not numeric or consecutive):
            result['count_check'] = 'match'
    _link_report_findings(result['findings'], finding_projects, items or [])
    return result


def extract_result(evidence: list[dict], doc_type: str, *, complete=False) -> dict:
    if doc_type == 'TABLE':
        return dict(doc_type='TABLE', fields=[], tables=[], review_issues=[issue('UNKNOWN','未获得表格结构，请重新识别或调整主体后上传。')], limitations=[])
    from .doc_profiles import SUPPORTED, profile
    additional = {}
    if doc_type in SUPPORTED - {'DIPLOMA', 'DEGREE_CERT', 'MEDICAL_REPORT'}:
        from .document_fields import extract_document_fields
        additional = extract_document_fields(evidence, doc_type)
    fields = additional['fields'] if 'fields' in additional else extract_fields(evidence, doc_type)
    if doc_type in SUPPORTED:
        metadata = {entry['key']: entry for entry in profile(doc_type, {f['key']: f.get('value') for f in fields})}
        for field in fields:
            if field['key'] in metadata:
                field.update(required=metadata[field['key']]['required'], editable=metadata[field['key']]['editable'])
    result = dict(doc_type=doc_type, fields=fields, review_issues=[], limitations=[])
    result['generic'] = dict(doc_subtype_guess=None, doc_subtype_confidence=None,
                             doc_subtype_confidence_method='unavailable', key_values=[],
                             full_text='\n\n'.join(block['text'] for block in evidence),
                             blocks=[dict(text=block['text'], page=block['page'], confidence=None,
                                          confidence_method='unavailable', **({'bbox': block['bbox']} if 'bbox' in block else {}))
                                     for block in evidence])
    if doc_type == 'MEDICAL_REPORT':
        items, limitations = extract_medical_items(evidence)
        report_summary = extract_report_summary(evidence, complete=complete, items=items)
        for item in items:
            if confirmed_abnormal(item) and item['diagnosis'] is None:
                item['review_issues'].append(issue('MISSING', '未获得可唯一关联的异常诊断，不能自动补写。'))
        result.update(basic_info={field['key']: field for field in fields}, items=items,
                      abnormal_summary=[item for item in items if confirmed_abnormal(item)],
                      report_summary=report_summary)
        from .medical_ledger import initialize_ledger
        initialize_ledger(result, evidence)
        if result['report_summary']['count_check'] == 'mismatch':
            result['review_issues'].append(issue('CONFLICT', '报告声明数量与该标题下清单不一致，请核对原页。'))
        result['limitations'].extend(limitations)
        if not complete or limitations:
            result['stats'] = dict(total=None, normal=None, abnormal=None, unknown=None, categories=[])
            result['limitations'].append('报告全量项目覆盖尚未确认，统计总量不可用；已提取项目不代表完整报告。')
            result['review_issues'].append(issue('INCOMPLETE_OUTPUT', '请核对整份报告的项目覆盖与原文。'))
        else:
            result['stats'] = medical_statistics(items)
    elif doc_type not in {'DIPLOMA', 'DEGREE_CERT'}:
        if doc_type in SUPPORTED:
            result.update(additional)
        else:
            result['review_issues'].append(issue('UNKNOWN', '尚不支持该材料的字段模板。'))
    return result
