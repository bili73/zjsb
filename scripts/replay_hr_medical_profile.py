"""Anonymous CPU-only native PDF replay of the approved HR field profile."""
import argparse
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
import probe_current_pipeline as base
from ocr_app.documents import decode_pages
from ocr_app.extraction import PERSONAL_KEYS, extract_result
from ocr_app.storage import Storage


def hashes():
    return {str(path.relative_to(ROOT)):base.digest(path.read_bytes()) for path in (
        ROOT/'backend/ocr_app/extraction.py',ROOT/'backend/ocr_app/documents.py',Path(__file__).resolve())}


def run(out):
    previous=ROOT/'output/concurrent-pipeline-20261008-v1'
    vault=base.read_only_storage(previous/'private/fixtures')
    frozen=(previous/'private/cases.enc').read_bytes()
    cases=[c for c in vault.unpack(frozen) if c['doc_type']=='MEDICAL_REPORT']
    if len(cases)!=3:
        raise base.ProbeError('MEDICAL_SET_CHANGED')
    private=Storage(out/'private/data')
    code_before=hashes()
    reports=[]
    for case in cases:
        data=vault.read(case['input_ref'])
        if base.digest(data)!=case['input_sha256']:
            raise base.ProbeError('SOURCE_BYTES_CHANGED')
        evidence=[];pages=0;pending_boxes=0
        begin=time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            for page in decode_pages(data):
                evidence.extend(page.evidence);pages+=1;pending_boxes+=len(page.ocr_boxes)
                page.image.close()
        decode_seconds=time.monotonic()-begin
        begin=time.monotonic()
        result=extract_result(evidence,'MEDICAL_REPORT',complete=False)
        mapping_seconds=time.monotonic()-begin
        (out/'private'/f"{case['id']}.enc").write_bytes(private.pack(result))
        fields={f['key']:f for f in result['fields']}
        known={(block['page'],block['region_id']) for block in evidence}
        def valid(source):
            bbox=source.get('bbox')
            return ((source.get('page'),source.get('region_id')) in known and isinstance(bbox,list)
                    and len(bbox)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in bbox)
                    and bbox[0]<bbox[2] and bbox[1]<bbox[3])
        grades=Counter('missing' if i['risk_grade'] is None else 'A' if i['risk_grade']=='A'
                       else 'slash' if i['risk_grade']=='/' else 'other' for i in result['items'])
        findings=result['report_summary']['findings']
        _, blood=base.score_case(case,result,[])
        report=dict(case_id=case['id'],input_sha256=case['input_sha256'],page_count=pages,
            decode_seconds=decode_seconds,mapping_seconds=mapping_seconds,native_evidence=len(evidence),
            pending_native_ocr_boxes=pending_boxes,model_calls=0,
            personal_fields={key:dict(filled=fields[key]['value'] is not None,
                page=(fields[key].get('source') or {}).get('page'),
                bbox_kind=(fields[key].get('source') or {}).get('bbox_kind'),
                source_valid=valid(fields[key]['source']) if fields[key].get('source') else None,
                review_reason=fields[key].get('review_reason')) for key in sorted(PERSONAL_KEYS)},
            item_count=len(result['items']),grade_counts=dict(grades),
            non_A_non_slash_items_by_page=dict(Counter(str(i['source']['page']) for i in result['items']
                if i['risk_grade'] is not None and i['risk_grade'] not in {'A','/'})),
            non_A_non_slash_confirmed_abnormal=sum(i['risk_grade'] is not None and i['risk_grade'] not in {'A','/'}
                and i['abnormal_flag'] in {'ABNORMAL','HIGH','LOW','POSITIVE'} for i in result['items']),
            missing_result_items=sum(not i['result_raw'] for i in result['items']),
            items_with_diagnosis=sum(i['diagnosis'] is not None for i in result['items']),
            diagnosis_sources_total=sum(len(i['diagnosis_sources']) for i in result['items']),
            diagnosis_sources_valid=sum(valid(s) for i in result['items'] for s in i['diagnosis_sources']),
            blood_reference_total=blood['field_total'],blood_reference_correct=blood['field_correct'],
            summary_scope=result['report_summary']['scope'],summary_declared=result['report_summary']['declared_count'],
            summary_findings=len(findings),summary_count_check=result['report_summary']['count_check'],
            summary_diagnoses=sum(f['diagnosis'] is not None for f in findings),
            summary_grades=sum(f['risk_grade'] is not None for f in findings),
            summary_results_linked=sum(f['result_raw'] is not None for f in findings),
            summary_results_missing=sum(f['result_raw'] is None for f in findings),
            summary_link_issue_counts=dict(Counter(i['code'] for f in findings for i in f['review_issues'])),
            result_sources_total=sum(len(f['result_sources']) for f in findings),
            result_sources_valid=sum(valid(s) for f in findings for s in f['result_sources']),
            stats_remain_unknown=all(result['stats'][k] is None for k in ('total','normal','abnormal','unknown')),
            input_hash_unchanged=base.digest(vault.read(case['input_ref']))==case['input_sha256'])
        reports.append(report)
    summary=dict(scope='Native evidence only; pending OCR is not executed. Counts are extraction observations, not full clinical or personal-field accuracy.',
        cases=reports,code_hashes=code_before,code_hashes_unchanged=code_before==hashes(),
        frozen_cases_ciphertext_sha256=base.digest(frozen),
        frozen_cases_unchanged=base.digest((previous/'private/cases.enc').read_bytes())==base.digest(frozen),
        personal_fields_filled=sum(f['filled'] for r in reports for f in r['personal_fields'].values()),
        personal_fields_observed=21,blood_reference_total=sum(r['blood_reference_total'] for r in reports),
        blood_reference_correct=sum(r['blood_reference_correct'] for r in reports),
        summary_findings=sum(r['summary_findings'] for r in reports),
        summary_results_linked=sum(r['summary_results_linked'] for r in reports),model_calls=0)
    base.save(out/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in {'cases','code_hashes'}},ensure_ascii=False))
    return 0 if summary['code_hashes_unchanged'] and summary['frozen_cases_unchanged'] and all(r['input_hash_unchanged'] for r in reports) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        return run(base.isolated_output(args.output))
    except Exception as error:
        print(json.dumps(dict(status='failed',code=str(error) if isinstance(error,base.ProbeError) else 'REPLAY_FAILED')))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
