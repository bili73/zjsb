"""The supplied ledger records report evidence, never an employment decision."""
import re
from bs4 import BeautifulSoup
from .table_format import table_html

GROUPS = {
    'blood_routine': ('血常规', {'血常规', '血常规检查', '血常规检验报告单'}),
    'urine_routine': ('尿常规', {'尿常规', '尿常规检查', '尿常规检验报告单', '尿液检验报告单'}),
    'ecg': ('心电图', {'心电图', '心电图检查', '心电图诊断科室', '心电图报告单'}),
    'dr_imaging': ('DR影像', {'DR影像', 'DR拍片', 'DR胸部正位检查', 'DR检查'}),
    'abdominal_ultrasound': ('腹部彩超', {'腹部彩超', '腹部彩超检查', '腹部超声', '腹部超声检查'}),
    'liver_function': ('肝功五项（生化检测）', {'肝功五项', '肝功能', '肝功能检查', '肝功能检验报告单', '肝功五项（生化检测）'}),
}
LEDGER_KEYS = ['name','gender','age','exam_date','institution','report_date','height','weight','blood_pressure',
               *GROUPS, 'exam_project_count']
HEADERS = ['序号','姓名','性别','年龄','体检日期','体检机构','报告日期','身高','体重','血压',
           '血常规','尿常规','心电图','DR影像','腹部彩超','肝功五项（生化检测）','体检项目数量','异常指标']
LIVER_ALIASES = {'ALT','AST','GGT','ALP','TBIL','DBIL','IBIL','IBIM','TP','ALB','GLO',
                 '丙氨酸氨基转移酶','谷丙转氨酶','天门冬氨酸氨基转移酶','谷草转氨酶','总胆红素','直接胆红素',
                 '间接胆红素','总蛋白','白蛋白','球蛋白','碱性磷酸酶','γ-谷氨酰转移酶'}


def compact(value):
    return re.sub(r'\s+', '', value or '').strip('#*：:').upper()


def project_names(value):
    if not isinstance(value, str):
        return []
    return list(dict.fromkeys(v.strip() for v in re.split('[；;\n]+', value) if v.strip()))


def _heading(text, catalogue):
    label = compact(text)
    for key, (_, names) in GROUPS.items():
        if label in {compact(n) for n in names}:
            return key
    if label in {'彩超检查', '超声检查'}:
        ultrasounds = [n for n in catalogue if '彩超' in n or '超声' in n]
        if len(ultrasounds) == 1 and compact(ultrasounds[0]) in {compact(n) for n in GROUPS['abdominal_ultrasound'][1]}:
            return 'abdominal_ultrasound'
    if label == '生化检验报告单':
        return 'biochemistry'
    return None


def attribute_groups(evidence, items, catalogue):
    """Clinical headings apply to measured tables, including adjacent-page continuation."""
    from .extraction import _grid, HEADER, _cell_evidence, source
    conclusions = {key: [] for key in GROUPS}
    active, previous_page = None, None
    ordered = sorted(enumerate(evidence), key=lambda p:(p[1].get('page',0),(p[1].get('bbox') or [0,0])[1],p[0]))
    for _, block in ordered:
        page = block.get('page')
        if previous_page is not None and page not in (previous_page, previous_page+1):
            active = None
        previous_page = page
        try:
            soup = BeautifulSoup(table_html(block['text']), 'html.parser')
        except ValueError:
            continue
        for node in soup.descendants:
            if getattr(node, 'name', None) == 'table' and node.find_parent('table') is None:
                grid = _grid(node)
                columns = None
                for index, row in enumerate(grid):
                    headers = [compact(c) for c in row]
                    matches = {key: [i for i,c in enumerate(headers) if c in {compact(h) for h in aliases}]
                               for key,aliases in HEADER.items()}
                    if matches['name'] and matches['result']:
                        columns = {key: indexes[0] for key,indexes in matches.items() if len(indexes)==1}
                        if len(matches['name'])!=1 or len(matches['result'])!=1:
                            columns = None
                        continue
                    if not columns:
                        continue
                    def cell(key):
                        i = columns.get(key, len(row))
                        return row[i] if i < len(row) else ''
                    key = active
                    if key == 'biochemistry':
                        key = 'liver_function' if compact(cell('name')) in LIVER_ALIASES or compact(cell('alias')) in LIVER_ALIASES else None
                    if key is None and compact(cell('name')) in {'心电图','DR胸部正位检查','DR影像'}:
                        key = _heading(cell('name'), catalogue)
                    if key not in GROUPS:
                        continue
                    if compact(cell('name')) == '小结':
                        value = ' '.join(cell('result').split())
                        if value:
                            conclusions[key].append((value, source(_cell_evidence(block,index,columns['result']),cell('result'))))
                        continue
                    matching = []
                    for item in items:
                        s = item.get('source') or {}
                        same_region = block.get('region_id') is not None and s.get('region_id') == block.get('region_id')
                        if same_region and s.get('page') == page and compact(item['name']) == compact(cell('name')) and item['result_raw']==cell('result').strip():
                            matching.append(item)
                    if len(matching)==1:
                        matching[0]['category'] = GROUPS[key][0]
            elif getattr(node,'name',None) is None and node.find_parent('table') is None:
                for line in str(node).splitlines():
                    key = _heading(line,catalogue)
                    if key:
                        active = key
                    elif (re.match(r'^[一二三四五六七八九十0-9]+[、.．:：]',compact(line))
                          or compact(line) in {'内科','内科检查','眼科','眼科常规','身高体重血压'}
                          or re.fullmatch(r'.{1,20}(?:检查|检验报告单|诊断科室)',compact(line))):
                        active = None
    return conclusions


def abnormal_text(item, diagnoses=()):
    name = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',item.get('name') or '')
    raw = ' '.join(str(item.get('result_raw') or '未关联检测结果').split())
    unit = item.get('unit')
    if unit and compact(unit) not in compact(raw):
        raw += ' '+unit
    diagnostic = list(dict.fromkeys(' '.join(d.split()) for d in [item.get('diagnosis'), *diagnoses] if d))
    return name+' '+raw+('（'+ '；'.join(diagnostic)+'）' if diagnostic else '')


def _derived(field, value, sources, *, input_field='items', conclusions=None):
    field.pop('absence_reason', None)
    field.update(value=value, value_origin='derived',
                 sources=sources, derivation=dict(method='medical_ledger',input_field=input_field),
                 confidence=None,confidence_method='unavailable')
    if conclusions is not None:
        field['derivation']['conclusions'] = [dict(value=v,source=s) for v,s in conclusions]
    field['need_review'] = bool(field.get('review_issues'))
    if sources:
        field['source'] = sources[0]
    else:
        field.pop('source',None)
    if field['need_review']:
        field['review_reason'] = field['review_issues'][0]['code']
    else:
        field.pop('review_reason',None)


def _catalogue_absences(result, catalogue):
    """Only a closed, numbered native catalogue proves that a test is not listed."""
    from .extraction import _medical_project_catalogue
    sources = catalogue.get('sources') or []
    if catalogue.get('value_origin') == 'manual' or not sources or any(s.get('extraction_method') != 'pdf_text' for s in sources):
        return set()
    evidence = result.get('generic', {}).get('blocks', [])
    observed, complete = _medical_project_catalogue(evidence)
    if not complete or project_names(observed.get('value')) != project_names(catalogue.get('value')):
        return set()
    patterns = dict(blood_routine=r'血常规|血液|血细胞', urine_routine=r'尿', ecg=r'心电',
                    dr_imaging=r'DR|X线|X射线|胸片', abdominal_ultrasound=r'彩超|超声', liver_function=r'肝功|生化')
    names = project_names(catalogue.get('value'))
    headings = {_heading(line, names) for b in evidence
                for line in BeautifulSoup(b['text'], 'html.parser').get_text('\n').splitlines()}
    absent = set()
    for key, pattern in patterns.items():
        candidates = [compact(n) for n in names if key != 'urine_routine' or not re.search(r'HCG|绒毛膜促性腺激素', compact(n))]
        if not any(re.search(pattern, n) for n in candidates) and key not in headings and not (key == 'liver_function' and 'biochemistry' in headings):
            absent.add(key)
    return absent


def _normal_row(item):
    if not item.get('source') or str(item.get('result_raw') or '').strip() in {'', '/'}:
        return False
    if any(p.get('code') == 'CONFLICT' for p in item.get('review_issues', [])):
        return False
    return ((item.get('abnormal_flag') == 'NORMAL' and item.get('abnormal_basis') in {'report_marker', 'reference_comparison'})
            or (item.get('abnormal_flag') == 'UNKNOWN' and item.get('abnormal_basis') == 'unknown'
                and item.get('risk_grade') == 'A' and not item.get('reported_abnormal_marker')))


def refresh_ledger(result):
    """Pure on a caller-owned result; manually supplied/absent values always win."""
    from .doc_profiles import profile
    from .extraction import _field, confirmed_abnormal, issue, medical_exclusion_reason
    fields = {f['key']:f for f in result.get('fields',[])}
    for meta in profile('MEDICAL_REPORT'):
        f = fields.setdefault(meta['key'], _field(meta['key'],meta['label'],[],meta['required']))
        f.update(required=meta['required'],editable=meta['editable'])
    items = result.get('items',[])
    catalogue = fields['exam_projects']
    absent_groups = _catalogue_absences(result, catalogue)
    count = fields['exam_project_count']
    _derived(count,len(project_names(catalogue.get('value'))) if project_names(catalogue.get('value')) else None,
             catalogue.get('sources') or ([catalogue['source']] if catalogue.get('source') else []),input_field='exam_projects')
    for key, names in {'height':{'身高'},'weight':{'体重'}}.items():
        field = fields[key]
        if field.get('value_origin')=='manual' or (field.get('value') is not None and field.get('value_origin')!='derived'):
            continue
        rows = [i for i in items if compact(i.get('name')) in names and i.get('result_raw') and i['result_raw'] != '/']
        candidates = [(' '.join(str(i['result_raw']).split())+(' '+i['unit'] if i.get('unit') else ''),i.get('source') or {},i['result_raw']) for i in rows]
        updated = _field(key,field['label'],candidates,False)
        field.update(updated)
        _derived(field,field['value'],[i['source'] for i in rows if i.get('source')])
    pressure = fields['blood_pressure']
    if pressure.get('value_origin')!='manual' and (pressure.get('value') is None or pressure.get('value_origin')=='derived'):
        upper = [i for i in items if compact(i.get('name')) in {'血压(收缩压)','血压（收缩压）','收缩压','SBP'} and i.get('result_raw') not in {None,'','/'}]
        lower = [i for i in items if compact(i.get('name')) in {'血压(舒张压)','血压（舒张压）','舒张压','DBP'} and i.get('result_raw') not in {None,'','/'}]
        pairs = [(a,b) for a in upper for b in lower if a.get('source') and b.get('source') and
                 a['source'].get('page') is not None and a['source'].get('page')==b['source'].get('page') and
                 a['source'].get('region_id') is not None and a['source'].get('region_id')==b['source'].get('region_id') and a.get('unit')==b.get('unit')]
        candidates = [(a['result_raw']+'/'+b['result_raw']+(' '+a['unit'] if a.get('unit') else ''),a['source'],a['result_raw']+'/'+b['result_raw']) for a,b in pairs]
        pressure.update(_field('blood_pressure',pressure['label'],candidates,False))
        _derived(pressure,pressure['value'],[i['source'] for pair in pairs for i in pair])
    for key,(label,_) in GROUPS.items():
        field = fields[key]
        if field.get('value_origin')=='manual' or (field.get('value') is not None and field.get('value_origin')!='derived'):
            continue
        conclusions = [(e['value'],e['source']) for e in field.get('derivation',{}).get('conclusions',[])]
        group_items = [i for i in items if i.get('category')==label and not medical_exclusion_reason(i.get('name'))]
        rows = [i for i in group_items if confirmed_abnormal(i)
                and (key!='liver_function' or i.get('source'))]
        value = '、'.join(abnormal_text(i) for i in rows) if rows else None
        source_list = [i['source'] for i in rows if i.get('source')]
        original = list(dict.fromkeys(v for v,s in conclusions))
        field['review_issues'] = [p for p in field.get('review_issues',[]) if p.get('rule_id')!='ledger_group_conflict']
        conflict = len(original)>1 or bool(rows and any(compact(v) in {'正常','未见异常','无异常'} for v in original))
        if conflict:
            problem = issue('CONFLICT','大项结论与检测结果或另一结论矛盾，请核对原文。')
            problem['rule_id']='ledger_group_conflict'
            field['review_issues'].append(problem)
            value = None
        elif not rows and len(original)==1:
            value = '未见异常' if compact(original[0]) in {'正常', '未见异常', '无异常'} else original[0]
        elif not original and group_items and all(_normal_row(i) for i in group_items):
            value = '已识别明细未见异常'
            source_list = [i['source'] for i in group_items]
        source_list += [s for v,s in conclusions]
        _derived(field,value,source_list,conclusions=conclusions)
        if not group_items and not original and not field.get('review_issues') and key in absent_groups:
            _derived(field, None, catalogue['sources'], input_field='exam_projects', conclusions=conclusions)
            field['absence_reason'] = 'NOT_ON_DOCUMENT'
    result['fields'] = [fields[m['key']] for m in profile('MEDICAL_REPORT')]
    result['basic_info'] = {f['key']:f for f in result['fields']}


def initialize_ledger(result, evidence):
    from .extraction import _field, source, _certificate_date
    fields = {f['key']:f for f in result['fields']}
    institution = fields['institution']
    if institution.get('value') is None and not institution.get('review_issues'):
        candidates = []
        for b in evidence:
            box = b.get('bbox') or []
            if b.get('page') != 1 or len(box) != 4:
                continue
            if not (.35 <= box[0] < box[2] <= 1 and .5 <= box[1] < box[3] <= .75):
                continue
            text = re.sub(r'\s+', '', b['text'])
            match = re.fullmatch(r'(普[潓惠]年华健康体检中心[（(][^()（）]{1,40}[)）])(?:[（(]\d{1,10}[)）])?',text)
            if match:
                candidates.append((match[1],b,b['text']))
        institution.update(_field('institution',institution['label'],candidates,False))
    date = fields['report_date']
    if isinstance(date.get('value'),str):
        normalized = _certificate_date(date['value'])
        if normalized:
            date['value'] = normalized
    conclusions = attribute_groups(evidence,result['items'],project_names(fields['exam_projects'].get('value')))
    for key, entries in conclusions.items():
        field = fields.setdefault(key,_field(key,GROUPS[key][0],[],False))
        field['derivation'] = dict(method='medical_ledger',input_field='items',conclusions=[dict(value=v,source=s) for v,s in entries])
    result['fields'] = list(fields.values())
    refresh_ledger(result)


def abnormal_cell(result):
    from .extraction import confirmed_abnormal, medical_exclusion_reason
    items = result.get('items',[])
    findings = result.get('report_summary',{}).get('findings',[])
    associated = []
    for f in findings:
        matches = [i for i in items if (f.get('result_item_id')==i['item_id'] if f.get('result_item_id') else i.get('source') and i['source'] in f.get('result_sources',[]))]
        associated.append((f,matches[0] if len(matches)==1 else None))
    entries = [abnormal_text(i,[f.get('diagnosis') for f,target in associated if target is i]) for i in items if confirmed_abnormal(i)]
    entries += [abnormal_text(dict(name=f.get('project_name') or f['text'],result_raw=f.get('result_raw'),diagnosis=f.get('diagnosis')))
                for f,target in associated if target is None and not medical_exclusion_reason(f.get('project_name'))]
    if entries:
        return '\n'.join(entries)
    stats = result.get('stats') or {}
    return '无' if stats.get('total') is not None and stats.get('unknown')==0 and stats.get('abnormal')==0 else None
