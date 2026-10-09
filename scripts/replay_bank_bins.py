"""Anonymous CPU replay of frozen card admission text against the pinned table."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
import probe_current_pipeline as base
from ocr_app.bank_bins import lookup_bank
from ocr_app.extraction import extract_result


def run(out):
    original=ROOT/'output/document-profile-samples-20261008-v2'
    vault=base.read_only_storage(original/'private/data')
    blobs=sorted(vault.blobs.glob('*.bin'),key=lambda p:p.stat().st_mtime_ns)
    hashes={p:base.digest(p.read_bytes()) for p in blobs}
    cases=[];snapshots=[]
    for path in blobs:
        try:value=json.loads(vault.decrypt(path.read_bytes()))
        except (ValueError,UnicodeDecodeError):continue
        if isinstance(value,list):cases=[c for c in value if c['doc_type']=='BANK_CARD']
        elif isinstance(value,dict) and value.get('result',{}).get('doc_type')=='BANK_CARD':snapshots.append((path,value['result']))
    if len(cases)!=3 or len(snapshots)!=3:raise base.ProbeError('CARD_SET_CHANGED')
    rows=[]
    for case,(snapshot,old) in zip(cases,snapshots):
        number=next(f for f in old['fields'] if f['key']=='card_number')
        if number['value']!=case['reference_number']:raise base.ProbeError('SNAPSHOT_ORDER_CHANGED')
        source=number['source'];evidence=dict(text=source['raw_text'],**{k:source[k] for k in ('page','region_id','bbox','bbox_kind','extraction_method') if k in source})
        began=time.perf_counter();result=extract_result([evidence],'BANK_CARD');elapsed=time.perf_counter()-began
        fields={f['key']:f for f in result['fields']};match=lookup_bank(number['value'])
        rows.append(dict(case=case['id'],snapshot_sha256=hashes[snapshot],input_sha256=case['input_sha256'],
            lookup_status=match['status'],reason_code=match['reason_code'],matched_prefix_length=len(match['prefix']) if match['prefix'] else None,
            derived_fields=[key for key,f in fields.items() if f.get('value_origin')=='derived'],
            no_forged_ocr_sources=all('source' not in fields[key] for key in ('bin_code','bank_name','card_type')),
            provenance_present=all(bool(fields[key].get('derivation')) for key in ('bin_code','bank_name','card_type')),
            card_number_unchanged=fields['card_number']['value']==number['value'],
            original_card_evidence_unchanged=fields['card_number']['source']==source,
            card_scheme_not_inferred=fields['card_scheme']['value'] is None,model_calls=0,mapping_seconds=elapsed))
    unchanged=all(base.digest(p.read_bytes())==sha for p,sha in hashes.items())
    success=unchanged and all(r['lookup_status']=='MATCHED' and all(r[k] for k in ('no_forged_ocr_sources','provenance_present','card_number_unchanged','original_card_evidence_unchanged','card_scheme_not_inferred')) for r in rows)
    sourcefiles=['backend/ocr_app/bank_bins.py','backend/ocr_app/document_fields.py','backend/ocr_app/validation.py','backend/ocr_app/review.py','openapi.yaml','scripts/replay_bank_bins.py']
    report=dict(status='passed' if success else 'failed',scope='Offline lookup coverage only, not bank-name accuracy or official issuer verification.',
        model_calls=0,cases=rows,covered=sum(r['lookup_status']=='MATCHED' for r in rows),total=len(rows),
        source_probe=original.name,frozen_blobs_unchanged=unchanged,
        dataset=json.loads((ROOT/'backend/ocr_app/data/bank_bins/provenance.json').read_text(encoding='utf-8')),
        code_sha256={p:base.digest((ROOT/p).read_bytes()) for p in sourcefiles})
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','model_calls','covered','total','frozen_blobs_unchanged')}))
    return 0 if success else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:sys.exit(run(base.isolated_output(args.output)))
    except Exception as error:
        print(json.dumps(dict(status='failed',code=str(error) if isinstance(error,base.ProbeError) else 'REPLAY_FAILED')));sys.exit(1)
