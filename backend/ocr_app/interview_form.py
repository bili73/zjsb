"""Source-bound applicant fields; never infer identity from nearby contacts."""
import re
import unicodedata

LABELS = {
    '身份证姓名': 'name', '姓名': 'name', '性别': 'gender', '年龄': 'age',
    '身份证号码': 'id_number', '身份证号': 'id_number', '公民身份号码': 'id_number',
    '手机号码': 'mobile_number', '手机号': 'mobile_number', '本人手机': 'mobile_number',
}
BOUNDARIES = ('婚姻状况', '子女情况', '最高学历', '紧急联系人', '紧急联络人', '电话',
              '籍贯', '民族', '政治面貌', '户籍地址', '目前住址', '工作经验', '签名', '填表日期', '出生年月')
EXCLUDED_SECTIONS = ('紧急联系人', '紧急联络人', '家庭成员', '家庭情况', '家属', '亲属', '工作经验')
APPLICANT_SECTIONS = ('基本信息', '个人信息', '应聘者信息', '本人信息')


def _applicant_tables(soup):
    tables = soup.find_all('table')
    section = None
    outside = ''
    selected = []
    sections = re.compile('|'.join((*EXCLUDED_SECTIONS, *APPLICANT_SECTIONS)))
    for element in soup.descendants:
        if element.find_parent('table') is not None:
            continue
        if isinstance(element, str):
            outside = (outside + re.sub(r'\s', '', element))[-120:]
            headings = list(sections.finditer(outside))
            if headings:
                section = headings[-1][0] in APPLICANT_SECTIONS
        elif element.name == 'table':
            text = re.sub(r'\s', '', element.get_text())
            anchored = any(label in text for label in ('身份证姓名', '身份证号码', '身份证号', '公民身份号码', '本人手机'))
            isolated = len(tables) == 1 and not any(label in text for label in (*EXCLUDED_SECTIONS, '关系'))
            if section is not False and (section is True or anchored or isolated):
                selected.append(element)
            if any(label in text for label in EXCLUDED_SECTIONS):
                section = False
            outside = ''
    return selected


def _value(key, raw):
    compact = re.sub(r'\s', '', unicodedata.normalize('NFKC', raw)).strip(':：|')
    if key == 'name':
        return compact if re.fullmatch(r'[\u4e00-\u9fff·]{2,12}', compact) else None
    if key == 'gender':
        if compact in {'男','女','M','F'}:
            return {'男':'M','女':'F'}.get(compact, compact)
        selected = set(re.findall(r'(?:[☑☒✓✔√]|\[[xX✓√]\])([男女])', compact))
        return {'男':'M','女':'F'}[next(iter(selected))] if len(selected) == 1 else None
    if key == 'age':
        match = re.fullmatch(r'(\d{1,3})岁?', compact)
        return int(match[1]) if match else None
    if key in {'id_number', 'mobile_number'}:
        compact = compact.replace('-', '').upper()
        # Retain malformed observed numbers for review, never checksum-repair them.
        return compact if re.fullmatch(r'[0-9]{5,24}[X]?', compact) else None
    return None


def extract_interview_fields(evidence):
    from bs4 import BeautifulSoup
    from .doc_profiles import profile
    from .extraction import _field, _cell_evidence, issue, source
    from .table_format import table_html
    from .validation import validate_field
    candidates = {f['key']: [] for f in profile('INTERVIEW_FORM')}
    misplaced = []
    marginal_names = []
    labels = sorted([*LABELS, *BOUNDARIES], key=len, reverse=True)
    pattern = re.compile('('+'|'.join('[ \\t]*'.join(re.escape(c) for c in label) for label in labels)+')')

    def add(key, raw, block):
        value = _value(key, raw)
        if value is not None:
            candidates[key].append((value, block, raw))
        elif key == 'name':
            number = _value('id_number', raw)
            if number and re.fullmatch(r'[0-9]{17}[0-9X]', number):
                misplaced.append((number, block, raw))

    for block in evidence:
        if block.get('_interview_complete') is False:
            continue
        raw = block['text']
        try:
            soup = BeautifulSoup(table_html(raw), 'html.parser')
        except ValueError:
            soup = BeautifulSoup(raw, 'html.parser')
        applicant_tables = _applicant_tables(soup)
        for ri, row in enumerate(soup.find_all('tr')):
            if row.find_parent('table') not in applicant_tables:
                continue
            cells = row.find_all(['td','th'], recursive=False)
            if any(label in re.sub(r'\s', '', row.get_text()) for label in EXCLUDED_SECTIONS):
                applicant_tables = [table for table in applicant_tables if table is not row.find_parent('table')]
                continue
            for ci, cell in enumerate(cells):
                label = re.sub(r'\s', '', cell.get_text()).strip(':：')
                if label not in LABELS:
                    continue
                values = []
                for following in cells[ci+1:]:
                    text = following.get_text(' ', strip=True)
                    if re.sub(r'\s', '', text).strip(':：') in labels:
                        break
                    values.append(text)
                # Multiple cells (ID digits/options) share a row source, not one cell.
                located = _cell_evidence(block, ri, ci+1 if len(values)==1 else None)
                add(LABELS[label], ' '.join(values), located)
        for table in soup.find_all('table'):
            table.decompose()
        # Explicit labels delimit free text; contact rows never become applicant fields.
        text = soup.get_text('\n', strip=True)
        for match in re.finditer(r'基本信息[ \t]+([\u4e00-\u9fff·]{2,12})[ \t]*(?:\n|$)', text):
            marginal_names.append((match[1], block, match[0]))
        section_boundary = '|'.join(r'\s*'.join(re.escape(c) for c in label) for label in EXCLUDED_SECTIONS)
        text = re.split(section_boundary, text)[0]
        matches = list(pattern.finditer(text))
        for i, match in enumerate(matches):
            label = re.sub(r'\s', '', match[0])
            if label in LABELS:
                end = matches[i+1].start() if i+1<len(matches) else len(text)
                add(LABELS[label], text[match.end():end].strip(' :：|\t\n'), block)
    resolved = {key: values[0][0] for key, values in candidates.items()
                if len({str(v[0]) for v in values}) == 1}
    fields = []
    for meta in profile('INTERVIEW_FORM'):
        key = meta['key']; values = candidates[key]
        f = _field(key, meta['label'], values, True)
        if values:
            f['sources'] = [source(b, raw) for _, b, raw in values]
        if len({str(v[0]) for v in values}) > 1:
            f['candidates'] = [dict(value=value, source=source(b, raw), reason='基本信息识别候选')
                               for value, b, raw in values]
        if key == 'id_number' and misplaced:
            f.setdefault('candidates', []).extend(dict(value=value, source=source(b, raw),
                reason='号码出现在姓名栏，请核对后采用') for value, b, raw in misplaced)
            f['review_issues'].append(issue('CONFLICT', '姓名栏内出现身份证号码候选，需对照原件确认归属。'))
        if key == 'name' and not values and marginal_names:
            f['candidates'] = [dict(value=value, source=source(b, raw), reason='基本信息栏外手写候选，请核对')
                               for value, b, raw in marginal_names]
        f['validation_checks'] = validate_field('INTERVIEW_FORM', key, f['value'], resolved)
        for check in f['validation_checks']:
            if check['status'] == 'FAIL' or check['status'] == 'UNKNOWN' and check['kind'] != 'OFFICIAL' and f['value'] is not None:
                f['review_issues'].append(issue('VALIDATION_FAILED', check['message'], True))
        f['need_review'] = bool(f['review_issues'])
        fields.append(f)
    return fields


def needs_alternate(block):
    fields = extract_interview_fields([block])
    return any(f['value'] is None or any(c['status']=='FAIL' or
               c['status']=='UNKNOWN' and c['kind']!='OFFICIAL' for c in f['validation_checks'])
               for f in fields)


def plan_interview_regions(image, box, check=lambda: None):
    from .table_recognition import locate_table_candidates, nearby_text
    crop = image.crop(box)
    fallback = [dict(box=box, task='ocr')]
    try:
        tables = locate_table_candidates(crop, check)
        lines = nearby_text(crop, tables, check)
    except Exception as exc:
        if getattr(exc, 'code', None):
            raise
        check()
        return fallback, ['基本信息区域未能定位，保留整页识别供人工核对。']
    check()
    anchors = [line for line in lines if any(label in re.sub(r'\s', '', line['text'])
               for label in ('身份证姓名', '身份证号码', '手机号码', '性别', '年龄'))]
    candidates = []
    for table in tables:
        x0, y0, x1, y1 = table['box']
        contained = [line for line in anchors if x0 <= (line['box'][0]+line['box'][2])/2 <= x1
                     and y0 <= (line['box'][1]+line['box'][3])/2 <= y1]
        if len(contained) >= 3:
            candidates.append((table, contained))
    if len(candidates) != 1:
        return fallback, ['基本信息表归属不唯一，保留整页识别供人工核对。']
    table, contained = candidates[0]
    x0, y0, x1, y1 = table['box']
    margin = max(16, round(crop.width * .015))
    headings = [line['box'][1] for line in lines if '基本信息' in line['text']
                and 0 <= y0-line['box'][1] < crop.height*.12]
    top = min([y0, *headings]) - margin
    stops = [line['box'][1] for line in lines if '最高学历' in line['text']
             and max(line_['box'][3] for line_ in contained) < line['box'][1] < y1]
    bottom = min(stops)-4 if stops else y1+margin
    area = (max(0, x0-margin), max(0, top), min(crop.width, x1+margin), min(crop.height, bottom))
    absolute = tuple(value + box[i % 2] for i, value in enumerate(area))
    return [dict(box=absolute, task='table')], ['识别聚焦基本信息区域；其余栏目保留在原件中，不作为本轮业务字段。']
