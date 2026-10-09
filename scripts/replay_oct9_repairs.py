"""CPU-only replay of frozen certificate OCR and an untouched medical PDF.

No resident model, production database, or historical output is modified.
The workbooks demonstrate the serializer; they are not new human review versions.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.documents import decode_pages
from ocr_app.extraction import extract_result, confirmed_abnormal
from ocr_app.exporting import workbook_bytes
from ocr_app.doc_profiles import PROFILES, profile, MEMBER_PROFILE


def run(audit_path, pdf_path, out):
    out.mkdir(parents=True, exist_ok=False)
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    data=pdf_path.read_bytes()
    assert hashlib.sha256(data).hexdigest()==audit['pdf_sha256'], 'SOURCE_CHANGED'
    evidence=[]; limits=[]; continuations=[]; boxes=0; count=0
    begin=time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):
        for page in decode_pages(data):
            evidence.extend(page.evidence);limits.extend(page.limitations);boxes+=len(page.ocr_boxes);count+=1
            continuations.extend(dict(page=b['page'],header_page=b['table_header_source']['page'],rows=len(b['table_rows'])-1)
                                 for b in page.evidence if b.get('table_recovery')=='split_header_continuation')
            page.image.close()
    decode_seconds=time.monotonic()-begin
    begin=time.monotonic()
    medical=extract_result(evidence,'MEDICAL_REPORT',complete=False)
    mapping_seconds=time.monotonic()-begin
    medical['_source_filename']=pdf_path.name
    urine={i['name']:i for i in medical['items'] if i['name'] in {'潜血','蛋白质'}}
    for name,value in [('潜血','+3'),('蛋白质','+1')]:
        assert urine[name]['result_raw']==value and urine[name]['risk_grade']=='E3'
        assert urine[name]['source']['page']==14
    findings=medical['report_summary']['findings']
    assert len(findings)==6 and all(f.get('result_item_id') and f.get('result_sources') for f in findings)
    summary=dict(model_calls=0,production_writes=0,pdf_sha256=audit['pdf_sha256'],pages=count,
        native_decode_seconds=decode_seconds,mapping_seconds=mapping_seconds,pending_ocr_boxes=boxes,
        item_count=len(medical['items']),abnormal_count=sum(confirmed_abnormal(i) for i in medical['items']),
        findings=len(findings),linked_findings=sum(bool(f.get('result_sources')) for f in findings),
        continued_tables=continuations,native_limitations=limits,certificates=[])
    results=[medical]
    for certificate in audit['certificates']:
        blocks=[dict(page=a['page'],region_id=a['region_id'],text=a['prediction']['text'],extraction_method='glm_ocr')
                for a in certificate['frozen_ocr'] if a.get('prediction',{}).get('termination_reason')=='eos']
        result=extract_result(blocks,'DIPLOMA',complete=True)
        values={f['key']:f['value'] for f in result['fields']}
        assert values['school_name'] and values['enroll_date'] and values['graduate_date'] and values['issue_date']
        result['_source_filename']=certificate['file_name']
        results.append(result)
        summary['certificates'].append(dict(source=certificate['file_name'],
            **{key:values[key] for key in ['school_name','enroll_date','graduate_date','issue_date']}))
    (out/'source-replay.xlsx').write_bytes(workbook_bytes(results))
    (out/'medical-result.json').write_text(json.dumps(medical,ensure_ascii=False,indent=2),encoding='utf-8')
    fixtures=[]
    for kind in PROFILES:
        r=extract_result([],kind)
        r['_source_filename']='合成测试_'+kind+'.png'
        for f in r.get('fields',[]):
            meta=next(m for m in profile(kind) if m['key']==f['key'])
            f['value']='2024-06' if meta['type']=='date' else 'M' if f['key']=='gender' else 28 if f['key']=='age' else '00123456789012345678' if 'number' in f['key'] or f['key']=='certificate_no' else '合成测试'
        if kind=='MEDICAL_REPORT':
            r['items']=medical['items'];r['report_summary']=medical['report_summary']
        if kind=='HOUSEHOLD_REGISTER':
            r['members']=[dict(fields=[dict(m,value='合成成员' if m['key']=='name' else None) for m in MEMBER_PROFILE])]
        if kind=='GENERIC':
            r['reviewed_generic']=dict(full_text='合成正文。'*160,key_values=[dict(key='合成字段',value='=1+2')])
        fixtures.append(r)
    (out/'synthetic-layout.xlsx').write_bytes(workbook_bytes(fixtures))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='certificates'},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.audit,args.pdf,args.out)
