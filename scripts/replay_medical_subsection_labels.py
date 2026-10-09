"""CPU-only comparison of the exact subsection-label fix on encrypted PDFs."""
import argparse
import contextlib
import csv
import io
import json
from pathlib import Path
import re
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
import probe_current_pipeline as base
from ocr_app.documents import decode_pages
from ocr_app.extraction import extract_result

GUARD="""                # A subsection summary is evidence, not an individual test item.
                if re.sub(r'\\s+', '', get('name')).rstrip(':：') == '小结':
                    continue
"""


def stable(value):
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k not in {'item_id','finding_id','issue_id'}}
    if isinstance(value,list):return [stable(v) for v in value]
    return value


def summary_label(item):
    return re.sub(r'\s+','',item['name']).rstrip(':：')=='小结'


def run(out):
    original=ROOT/'output/current-pipeline-acceptance-20261008-v2'
    vault=base.read_only_storage(original/'private/fixtures')
    frozen=(original/'private/cases.enc').read_bytes()
    cases=[case for case in vault.unpack(frozen) if case['doc_type']=='MEDICAL_REPORT']
    if len(cases)!=3:raise base.ProbeError('MEDICAL_SET_CHANGED')
    code=(ROOT/'backend/ocr_app/extraction.py').read_text(encoding='utf-8')
    if code.count(GUARD)!=1:raise base.ProbeError('BASELINE_DIFF_CHANGED')
    # Reconstruct only the immediate pre-fix implementation in memory; all other
    # extraction rules are identical. No old sample or production file is edited.
    before_code=code.replace(GUARD,'')
    before=types.ModuleType('ocr_app._subsection_before')
    before.__package__='ocr_app'
    exec(compile(before_code,'<in-memory-pre-fix-extraction>','exec'),before.__dict__)
    rows=[]
    for case in cases:
        data=vault.read(case['input_ref'])
        if base.digest(data)!=case['input_sha256']:raise base.ProbeError('SOURCE_BYTES_CHANGED')
        began=time.perf_counter();evidence=[];page_count=0;pending=0
        with contextlib.redirect_stdout(io.StringIO()):
            for page in decode_pages(data):
                evidence.extend(page.evidence);page_count+=1;pending+=len(page.ocr_boxes)
                page.image.close()
        decode_seconds=time.perf_counter()-began
        began=time.perf_counter()
        old=before.extract_result(evidence,'MEDICAL_REPORT',complete=False)
        new=extract_result(evidence,'MEDICAL_REPORT',complete=False)
        mapping_seconds=time.perf_counter()-began
        removed=[i for i in old['items'] if summary_label(i)]
        ordinary=[i for i in old['items'] if not summary_label(i)]
        summary=new['report_summary']
        _,blood=base.score_case(case,new,[])
        row=dict(case=case['id'],input_sha256=case['input_sha256'],pages=page_count,
            model_calls=0,pending_native_ocr_boxes=pending,items_before=len(old['items']),items_after=len(new['items']),
            summary_labels_removed=len(removed),summary_labels_remaining=sum(summary_label(i) for i in new['items']),
            ordinary_items_unchanged=stable(ordinary)==stable(new['items']),
            ordinary_abnormal_unchanged=stable([i for i in old['abnormal_summary'] if not summary_label(i)])==stable(new['abnormal_summary']),
            generic_evidence_unchanged=old['generic']==new['generic'],
            original_evidence_blocks_retained=[b['text'] for b in evidence]==[b['text'] for b in new['generic']['blocks']],
            report_summary_unchanged=stable(old['report_summary'])==stable(summary),
            summary_declared=summary['declared_count'],summary_findings=len(summary['findings']),summary_count_check=summary['count_check'],
            blood_reference_total=blood['field_total'],blood_reference_correct=blood['field_correct'],
            input_hash_unchanged=base.digest(vault.read(case['input_ref']))==case['input_sha256'],
            native_decode_seconds=decode_seconds,both_mappings_seconds=mapping_seconds)
        rows.append(row)
    checks=['ordinary_items_unchanged','ordinary_abnormal_unchanged','generic_evidence_unchanged',
            'original_evidence_blocks_retained','report_summary_unchanged','input_hash_unchanged']
    success=all(all(r[k] for k in checks) and r['summary_labels_remaining']==0 and
                r['items_before']-r['items_after']==r['summary_labels_removed'] for r in rows)
    source_unchanged=(original/'private/cases.enc').read_bytes()==frozen
    result=dict(status='passed' if success and source_unchanged else 'failed',model_calls=0,cases=rows,
        method='Decode frozen source PDFs once; compare current extraction to the identical source with only the exact summary-label guard removed, both in memory. No reference value participates in extraction.',
        scope='Native mapping regression, not new OCR inference or full-report accuracy.',
        limitations=['Subsection text remains in original generic blocks/full_text and page evidence; no separate structured subsection DTO is created.',
                      'An unlinked subsection abnormal statement is not invented as a laboratory result or added to the independent follow-up list.'],
        baseline_extraction_sha256=base.digest(before_code.encode()),extraction_sha256=base.digest(code.encode()),
        script_sha256=base.digest(Path(__file__).read_bytes()),frozen_cases_unchanged=source_unchanged,
        frozen_cases_ciphertext_sha256=base.digest(frozen))
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(dict(status=result['status'],model_calls=0,cases=[{k:r[k] for k in ('case','items_before','items_after','summary_labels_removed','summary_findings','summary_count_check')} for r in rows])))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:sys.exit(run(base.isolated_output(args.output)))
    except Exception as error:
        print(json.dumps(dict(status='failed',code=str(error) if isinstance(error,base.ProbeError) else 'REPLAY_FAILED')))
        sys.exit(1)
