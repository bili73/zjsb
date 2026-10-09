"""Conservative label/geometry extraction for additional document families."""
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from .doc_profiles import profile, MEMBER_PROFILE
from .validation import validate_field

ALIASES = {
    'id_number': ('公民身份号码','公民身份证号码','身份证号码','身份证号'),
    'name': ('姓名','持有人姓名','Name'), 'gender': ('性别','Sex','Gender'),
    'birth_date': ('出生日期','出生年月日','出生','Date of Birth'),
    'address': ('住址','地址'), 'issuing_authority': ('签发机关','签发机构','Authority'),
    'valid_from': ('有效期限起','有效期起'), 'valid_to': ('有效期限止','有效期至'),
    'company_name': ('名称','企业名称'), 'company_type': ('类型','主体类型'),
    'legal_representative': ('法定代表人','经营者','投资人','执行事务合伙人','负责人'),
    'established_date': ('成立日期','注册日期'), 'registered_address': ('住所','经营场所','主要经营场所'),
    'issue_date': ('核准日期','签发日期','Date of Issue'),
    'householder': ('户主姓名','户主'), 'issued_by': ('签发机关','户口登记机关'),
    'relation_to_householder': ('与户主关系','户主或与户主关系'),
    'school_name': ('学校名称','毕业院校','Institution'), 'major': ('专业名称','专业','Major'),
    'education_level': ('学历层次','层次','Level'), 'enroll_date': ('入学日期','入学时间','Date of Enrollment'),
    'graduate_date': ('毕（结）业日期','毕(结)业日期','毕业日期','毕业时间','Date of Graduation'),
    'graduate_conclusion': ('毕（结）业结论','毕(结)业结论','毕（结）业','毕(结)业'),
    'principal': ('校（院）长姓名','校(院)长姓名'),
    'valid_until': ('验证有效期至','验证有效期','Valid Until'),
    'passport_number': ('护照号码','护照号','Passport No.','Passport Number'),
    'nationality': ('国籍','Nationality'), 'expiry_date': ('有效期至','Date of Expiry','Expiration Date'),
    'surname': ('姓','Surname'), 'given_names': ('名','Given Names'),
    'document_code': ('类型','证件代码','Type'), 'issuing_country': ('签发国','Issuing State'),
}


def _normalize(key, value):
    from .extraction import _certificate_date
    value=value.strip(' \t\n:：|')
    if not value: return None
    if key=='duration':
        compact=re.sub(r'\s','',value)
        chinese=r'(?:[零〇一二三四五六七八九两]|十[一二三四五六七八九]?|[二三四五六七八九]十[一二三四五六七八九]?)'
        if re.fullmatch(r'(?:[0-9０-９]+(?:[.．][0-9０-９]+)?|'+chinese+r'(?:点[零〇一二三四五六七八九]+)?)年',compact):
            return compact
    if key=='gender': return {'男':'M','女':'F','Male':'M','Female':'F','M':'M','F':'F','<':'X'}.get(value,value)
    if key.endswith('_date') or key in {'valid_from','valid_to','valid_until','business_term_start','business_term_end'}:
        if value=='长期': return value
        normalized = _certificate_date(value.replace('/','-').replace('.','-'))
        return normalized or value
    if key in {'card_number','id_number','unified_social_credit_code'}:
        if key=='card_number':value=unicodedata.normalize('NFKC',value)
        return re.sub(r'[\s-]' if key=='card_number' else r'\s','',value)
    return value


def _candidates(evidence, metadata):
    from .extraction import _cell_evidence
    aliases={}
    for f in metadata:
        for label in (f['label'],*ALIASES.get(f['key'],())):
            aliases[re.sub(r'\s','',label)] = f['key']
    candidates={f['key']:[] for f in metadata}
    def add(key, value, block, raw=None):
        normalized=_normalize(key,value)
        if normalized is not None: candidates[key].append((normalized,block,raw if raw is not None else value))
    label_patterns = ['[ \t]*'.join(re.escape(c) for c in a) for a in sorted(aliases,key=len,reverse=True)]
    pattern=re.compile(r'(?<![A-Za-z\u4e00-\u9fff])('+'|'.join(label_patterns)+r')(?:[ \t]*[:：][ \t]*|[ \t]*\n|[ \t]+|$)') if aliases else None
    # Table cells preserve rows. Free text requires an explicit label boundary.
    for block in evidence:
        soup=BeautifulSoup(block['text'],'html.parser') if '<table' in block['text'].lower() else None
        if soup:
            for ri,tr in enumerate(soup.find_all('tr')):
                cells=tr.find_all(['td','th'],recursive=False)
                for ci,cell in enumerate(cells[:-1]):
                    label=re.sub(r'\s','',cell.get_text(' ',strip=True)).rstrip(':：')
                    if label in aliases:
                        value=cells[ci+1].get_text(' ',strip=True)
                        if re.sub(r'\s','',value).rstrip(':：') not in aliases:
                            add(aliases[label],value,_cell_evidence(block,ri,ci+1),cell.get_text(' ',strip=True)+'：'+value)
            for table in soup.find_all('table'): table.extract()
            text=soup.get_text('\n',strip=True)
        else: text=block['text']
        if not pattern: continue
        matches=list(pattern.finditer(text))
        for i,m in enumerate(matches):
            key=aliases[re.sub(r'\s','',m[1])]
            end=matches[i+1].start() if i+1<len(matches) else len(text)
            value=text[m.end():end].strip()
            # A single value line is safe; multiline free-form licence text is explicit.
            lines=value.splitlines()
            if lines and key not in {'business_scope','address','registered_address'}:
                value=lines[0]
            if value: add(key,value,block,m[1]+'：'+value)
    # Native PDF labels and their values may be separate aligned blocks.
    for label_block in evidence:
        label=re.sub(r'\s','',label_block['text']).rstrip(':：')
        if label not in aliases or not label_block.get('bbox'): continue
        box=label_block['bbox']; matches=[]
        for value_block in evidence:
            other=value_block.get('bbox')
            if value_block is label_block or value_block.get('page')!=label_block.get('page') or not other: continue
            overlap=min(box[3],other[3])-max(box[1],other[1])
            if overlap>0 and other[0]>=box[2]-.005:
                token=re.sub(r'\s','',value_block['text']).rstrip(':：')
                if token not in aliases: matches.append(value_block)
        if len(matches)==1:
            add(aliases[label],matches[0]['text'],matches[0],label_block['text']+'：'+matches[0]['text'])
    if 'valid_from' in candidates and 'valid_to' in candidates:
        date_token=r'[0-9]{4}[.年/-][0-9]{1,2}[.月/-][0-9]{1,2}日?'
        for block in evidence:
            match=re.search(r'有效期限\s*[:：]?\s*('+date_token+r')\s*[-—至]\s*('+date_token+r'|长期)',block['text'])
            if match:
                add('valid_from',match[1],block,match[0])
                add('valid_to',match[2],block,match[0])
    return candidates


def _build(evidence, doc_type, metadata=None):
    from .extraction import _field, issue
    metadata=metadata or profile(doc_type)
    candidates=_candidates(evidence,metadata)
    resolved={key:values[0][0] for key,values in candidates.items() if len({str(v[0]) for v in values})==1}
    if metadata==profile(doc_type): metadata=profile(doc_type,resolved)
    result=[]
    for meta in metadata:
        f=_field(meta['key'],meta['label'],candidates[meta['key']],meta['required'])
        f['validation_checks']=validate_field(doc_type,f['key'],f['value'],resolved)
        for c in f['validation_checks']:
            if c['status']=='FAIL':
                f['review_issues'].append(issue('VALIDATION_FAILED',c['message']))
            elif c['status']=='UNKNOWN' and c['kind']!='OFFICIAL' and f['value'] is not None:
                problem=issue('VALIDATION_FAILED',c['message'],True)
                if c['rule_id'].startswith('bin_reference_'):problem['rule_id']=c['rule_id']
                f['review_issues'].append(problem)
        f['need_review']=bool(f['review_issues'])
        if f['review_issues']:f['review_reason']=f['review_issues'][0]['code']
        if not meta['editable']:
            f['review_issues']=[]
            f['need_review']=False
            f.pop('review_reason',None)
        result.append(f)
    return result


def extract_document_fields(evidence, doc_type):
    from .extraction import _field, issue, plain
    texts='\n'.join(b['text'] for b in evidence)
    out={'fields':[]}
    if doc_type in {'DIPLOMA','DEGREE_CERT','MEDICAL_REPORT'}:
        from .extraction import extract_fields
        out['fields']=extract_fields(evidence,doc_type)
        return out
    if doc_type=='GENERIC':
        blocks=[dict(text=plain(b['text']),page=b['page'],confidence=None,confidence_method='unavailable',**({'bbox':b['bbox']} if b.get('bbox') else {})) for b in evidence]
        kv=[]
        for b in blocks:
            for line in b['text'].splitlines():
                m=re.fullmatch(r'([^:：\n]{1,40})[:：]\s*(\S.*)',line)
                if m:kv.append(dict(key=m[1].strip(),value=m[2],confidence=None,confidence_method='unavailable'))
        for b in evidence:
            if '<table' not in b['text'].lower(): continue
            for row in BeautifulSoup(b['text'],'html.parser').find_all('tr'):
                cells=row.find_all(['td','th'],recursive=False)
                if len(cells)==2:
                    key,value=(c.get_text(' ',strip=True) for c in cells)
                    if key and value and len(key)<=40:
                        kv.append(dict(key=key,value=value,confidence=None,confidence_method='unavailable'))
        out.update(generic=dict(full_text='\n'.join(b['text'] for b in blocks),blocks=blocks,key_values=kv,
            doc_subtype_guess=None,doc_subtype_confidence=None,doc_subtype_confidence_method='unavailable'),
            review_issues=[issue('CONFIDENCE_UNAVAILABLE','通用识别内容与完整覆盖需人工核对。',True)] if any(b['text'].strip() for b in blocks) else [issue('MISSING','没有可靠识别的正文内容。')])
        return out
    if doc_type=='XUEXIN_DIPLOMA_TABLE':
        compact=re.sub(r'\s','',texts)
        target='教育部学历证书电子注册备案表' in compact or 'OnlineVerificationReportofHigherEducationQualificationCertificate' in compact
        other=any(s in compact for s in ['教育部学籍在线验证报告','中国高等教育学位在线验证报告','中国高等教育学历认证报告','中国高等教育学位认证报告'])
        kind='DIPLOMA_TABLE' if target and not other else 'OTHER_REPORT' if other and not target else 'UNKNOWN'
        out['fields']=_build(evidence if kind=='DIPLOMA_TABLE' else [],doc_type)
        if kind!='DIPLOMA_TABLE':out['review_issues']=[issue('UNSUPPORTED_DOC_TYPE','报告种类不是已确认的学历证书电子注册备案表。')]
        else:
            language='zh' if '教育部学历证书电子注册备案表' in compact else 'en'
            for i,f in enumerate(out['fields']):
                if f['key']=='report_language':
                    b=next(b for b in evidence if ('教育部' in b['text'] or 'Online' in b['text']))
                    out['fields'][i]=_field('report_language','报告语种',[(language,b,language)],True)
        values={f['key']:f['value'] for f in out['fields']}
        code=values.get('online_verification_code');until=values.get('valid_until')
        compatible=bool(code and re.fullmatch(r'(?:[A-Za-z0-9]{12}|[A-Za-z0-9]{16})',re.sub(r'\s','',code)))
        expired=None
        if until:
            try:expired=datetime.strptime(until,'%Y-%m-%d').date()<datetime.now(ZoneInfo('Asia/Shanghai')).date()
            except ValueError:until=None
        out['xuexin_info']=dict(report_kind=kind,report_kind_confidence=None,report_kind_confidence_method='unavailable',
            online_verification_code=code,online_verification_code_normalized=re.sub(r'\s','',code) if code else None,
            code_valid=True if compatible else None,verify_url='https://www.chsi.com.cn/xlcx/bgcx.jsp',valid_until=until,
            is_expired=expired,manual_verify_status='NOT_CHECKED',source_kind='pdf_text' if evidence and all(b.get('extraction_method')=='pdf_text' for b in evidence) else 'unknown',likely_truncated=None)
        if values.get('report_language'):out['xuexin_info']['report_language']=values['report_language']
        return out
    if doc_type=='HOUSEHOLD_REGISTER':
        member_pages={b['page'] for b in evidence if '常住人口登记卡' in re.sub(r'\s','',b['text'])}
        out['fields']=_build([b for b in evidence if b['page'] not in member_pages],doc_type)
        out['members']=[{f['key']:f for f in _build([b for b in evidence if b['page']==p],doc_type,MEMBER_PROFILE)} for p in sorted(member_pages)]
        if not member_pages:out['review_issues']=[issue('MISSING','未确认常住人口登记卡页面，需核对材料完整性。')]
        return out
    out['fields']=_build(evidence,doc_type)
    if doc_type=='BANK_CARD':
        candidates=[]
        for b in evidence:
            for m in re.finditer(r'(?<![0-9０-９])(?:[0-9０-９][ \t\u3000－-]*){13,19}(?![ \t\u3000－-]*[0-9０-９])',plain(b['text'])):
                candidates.append((_normalize('card_number',m[0]),b,m[0]))
        f=_field('card_number','卡号',candidates,True)
        f['validation_checks']=validate_field(doc_type,'card_number',f['value'])
        if f['value'] is not None:
            f['review_issues'].append(issue('VALIDATION_FAILED','离线匹配不验证账户或Luhn适用性，请对照原件确认卡号。',True))
        if any(c['status']=='FAIL' for c in f['validation_checks']):f['review_issues'].append(issue('VALIDATION_FAILED','卡号本地校验失败，不能自动改号。'))
        for i,old in enumerate(out['fields']):
            if old['key']=='card_number':out['fields'][i]=f
        refresh_bank_fields(out)
    if doc_type=='PASSPORT':
        lines=[]
        for b in evidence:
            for line in plain(b['text']).splitlines():
                if re.fullmatch(r'[A-Z0-9<]{44}',line.strip()):lines.append((line.strip(),b))
        pairs=[(lines[i],lines[i+1]) for i in range(len(lines)-1) if lines[i][0].startswith('P') and lines[i][1]['page']==lines[i+1][1]['page']]
        if len(pairs)==1:
            (a,ab),(b,bb)=pairs[0];mrz=a+'\n'+b
            names=a[5:].rstrip('<').split('<<',1)
            derived={'mrz':mrz,'document_code':a[:2].rstrip('<'),'issuing_country':a[2:5],
                'passport_number':b[:9].rstrip('<'),'nationality':b[10:13],'gender':b[20] if b[20]!='<' else 'X',
                'surname':names[0].replace('<',' '),'given_names':names[1].replace('<',' ') if len(names)>1 else ''}
            # YY dates have no century; retain MRZ evidence, do not invent dates.
            for i,f in enumerate(out['fields']):
                if derived.get(f['key']):
                    c=[(derived[f['key']],ab if f['key'] in {'surname','given_names','document_code','issuing_country'} else bb,derived[f['key']])]
                    if f['value'] is not None:c.append((f['value'],f.get('source',bb),f['value']))
                    meta=next(m for m in profile(doc_type) if m['key']==f['key'])
                    out['fields'][i]=_field(f['key'],f['label'],c,meta['required'])
                    out['fields'][i]['validation_checks']=validate_field(doc_type,f['key'],out['fields'][i]['value'])
                    if any(c['status']=='FAIL' for c in out['fields'][i]['validation_checks']):
                        out['fields'][i]['review_issues'].append(issue('VALIDATION_FAILED','机读区校验未通过，需核对原始字符。'))
            out['passport']=dict(format='TD3',mrz_checks=validate_field(doc_type,'mrz',mrz))
        else:out['passport']=dict(format='UNKNOWN',mrz_checks=validate_field(doc_type,'mrz',None))
    return out


def refresh_bank_fields(result, *, pan_changed=False):
    """Recompute automatic values; community disagreement never overrides a human."""
    from .bank_bins import lookup_bank, derivation
    from .extraction import issue
    fields={field['key']:field for field in result['fields']}
    values={key:field.get('value') for key,field in fields.items()}
    match=lookup_bank(values.get('card_number'))
    derived_values={'bin_code':match['prefix'],'bank_name':match['bank_name'],'card_type':match['card_type']}
    for key,value in derived_values.items():
        target=fields[key]
        was_derived=target.get('value_origin')=='derived'
        if pan_changed:
            target['accepted_validation_rules']=[r for r in target.get('accepted_validation_rules',[]) if not r.startswith('bin_reference_')]
            target['review_issues']=[p for p in target.get('review_issues',[]) if not p.get('rule_id','').startswith('bin_reference_')]
        conflicting=any(p['code'] in {'CONFLICT','MULTI_CANDIDATES'} for p in target.get('review_issues',[]))
        automatic=(was_derived or key=='bin_code' or
                   (target.get('value') in (None,'') and target.get('value_origin')!='manual' and not conflicting))
        if automatic:
            target.update(value=value,value_origin='derived' if value is not None else 'recognized',
                          confidence=None,confidence_method='unavailable',review_issues=[],need_review=False)
            for old in ('source','candidates','derivation','review_reason','absence_reason'):
                target.pop(old,None)
            if pan_changed:target.update(reviewed=False,reviewed_by=None)
            if value is not None:target['derivation']=derivation(match)
            target['validation_checks']=[dict(kind='FORMAT',status='PASS' if value is not None else 'UNKNOWN',
                rule_id='bin_snapshot_v1',message='仅离线社区表匹配，不代表官方发卡核验。' if value is not None else '离线表未唯一匹配，不推断。')]
            continue
        # Explicit OCR conflicts remain untouched. A single explicit/manual value
        # may differ from a stale community table and can be confirmed as such.
        if conflicting:continue
        target.pop('derivation',None)
        checks=validate_field('BANK_CARD',key,target.get('value'),values)
        target['validation_checks']=checks
        unknown={c['rule_id']:c for c in checks if c['status']=='UNKNOWN' and c['rule_id'].startswith('bin_reference_')}
        target['review_issues']=[p for p in target.get('review_issues',[]) if not p.get('rule_id','').startswith('bin_reference_') or p['rule_id'] in unknown]
        for rule,check in unknown.items():
            if rule in target.get('accepted_validation_rules',[]) or any(p.get('rule_id')==rule for p in target['review_issues']):continue
            problem=issue('VALIDATION_FAILED',check['message'],True);problem['rule_id']=rule
            target['review_issues'].append(problem)
        target['need_review']=bool(target['review_issues'])
        if 'review_reason' in target:target['review_reason']=target['review_issues'][0]['code'] if target['review_issues'] else None
