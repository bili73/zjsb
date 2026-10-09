"""Fresh serial certificate API test using a separately frozen visual fixture."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib,json,sys
from pathlib import Path
import probe_current_pipeline as probe
from ocr_app.doc_profiles import profile
from ocr_app.storage import Storage
from schema_extraction import score

ROOT=probe.ROOT

def reference_for(fields,original,overrides):
    keys={f['key'] for f in fields}
    if set(overrides)-keys:
        raise probe.ProbeError('UNKNOWN_REFERENCE_FIELD')
    reference={key:deepcopy(original[key]) for key in keys if key in original}
    reference.update(deepcopy(overrides))
    if set(reference)!=keys or any(v.get('status') not in {'present','absent','uncertain'} or
            (v['status']=='present' and v.get('value') in (None,'')) for v in reference.values()):
        raise probe.ProbeError('INCOMPLETE_REFERENCE')
    return reference

def freeze(out,supplied):
    vault=Storage(out/'private/fixtures')
    old_protocol,old_storage,old=probe.frozen(probe.CERT)
    cases=[]
    for s in old['samples']:
        if s['doc_type'] not in {'DIPLOMA','DEGREE_CERT'}:continue
        data=old_storage.read(s['image_ref'])
        if probe.digest(data)!=s['input_sha256']:raise probe.ProbeError('INPUT_CHANGED')
        fields=profile(s['doc_type'])
        reference=reference_for(fields,s['reference'],supplied['frozen_overrides'].get(s['id'],{}))
        cases.append(dict(id=s['id'],doc_type=s['doc_type'],suffix='.png',input_ref=vault.put(data),
            input_sha256=probe.digest(data),source_sha256=s['source_sha256'],reference=reference,fields=fields,
            legacy_reference=s['reference'],legacy_fields=old['templates'][s['doc_type']],reference_scope='historical_control'))
    for s in supplied['new_samples']:
        path=Path(s['path']);data=path.read_bytes();fields=profile('DIPLOMA')
        cases.append(dict(id=s['id'],doc_type='DIPLOMA',suffix=path.suffix,input_ref=vault.put(data),
            input_sha256=probe.digest(data),source_sha256=probe.digest(data),source_path=str(path),
            reference=reference_for(fields,{}, {k:dict(status='present',value=v) for k,v in s['values'].items()}),
            fields=fields,reference_scope='current_original'))
    if len(cases)!=7 or len({s['id'] for s in cases})!=7 or len({s['source_sha256'] for s in cases})!=7:
        raise probe.ProbeError('CASE_IDENTITY_OR_DUPLICATE')
    encoded=vault.pack(cases);(out/'private/cases.enc').write_bytes(encoded)
    code=sorted([*ROOT.glob('backend/**/*.py'),ROOT/'scripts/schema_extraction.py',ROOT/'scripts/probe_current_pipeline.py',Path(__file__).resolve(),ROOT/'SPEC.md',ROOT/'openapi.yaml'])
    sources=[probe.CERT/'protocol.json',probe.CERT/'private/fixture.enc']
    counts=Counter(v['status'] for s in cases for v in s['reference'].values())
    protocol=dict(probe='current_pipeline_acceptance',experiment='diploma_accuracy_refresh',schema_version=2,mode='single_resident',cases_sha256=probe.digest(encoded),
        cases=[{k:s[k] for k in ('id','doc_type','input_sha256','source_sha256','reference_scope')} for s in cases],
        code_hashes={str(p.relative_to(ROOT)):probe.digest(p.read_bytes()) for p in code},
        source_hashes={str(p.relative_to(ROOT)):probe.digest(p.read_bytes()) for p in sources},
        checkpoints={name:json.loads((ROOT/'models'/name/'download_manifest.json').read_text())['revision'] for name in ('glm-ocr','paddleocr-vl')},
        certificate_references=dict(counts),max_new_tokens=4096,task_budget_seconds=180,
        scoring='Current profiles, visually labelled printed interval endpoints; legacy present39 scored separately. References frozen before inference; original references unchanged.',
        scope='Six real diplomas and one degree control; provisional agent visual labels and rule-development samples, not held-out/general accuracy or Mac performance.')
    probe.save(out/'protocol.json',protocol)
    return protocol

def prepared(out,**kwargs):
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    if protocol['mode']!='single_resident':raise probe.ProbeError('RESIDENCY_CHANGED')
    vault=probe.read_only_storage(out/'private/fixtures');encoded=(out/'private/cases.enc').read_bytes()
    if probe.digest(encoded)!=protocol['cases_sha256']:raise probe.ProbeError('REFERENCE_CHANGED')
    cases=vault.unpack(encoded)
    for s in cases:
        if probe.digest(vault.read(s['input_ref']))!=s['input_sha256']:raise probe.ProbeError('INPUT_CHANGED')
        if s.get('source_path') and probe.digest(Path(s['source_path']).read_bytes())!=s['source_sha256']:
            raise probe.ProbeError('ORIGINAL_CHANGED')
    for group in ('code_hashes','source_hashes'):
        if any(probe.digest((ROOT/p).read_bytes())!=sha for p,sha in protocol[group].items()):raise probe.ProbeError('PROVENANCE_CHANGED')
    return vault,cases,protocol

def summarize(out):
    vault,cases,protocol=prepared(out)
    tasks=json.loads((out/'tasks.json').read_text(encoding='utf-8'))
    fields=[];legacy=[]
    for case in cases:
        saved=out/'private'/(case['id']+'.enc')
        result=vault.unpack(saved.read_bytes())['result'] if saved.exists() else {}
        rows,_=probe.score_case(case,result,[])
        if not saved.exists():
            for row in rows:row['outcome']='not_run'
        fields.extend(dict(doc_type=case['doc_type'],reference_scope=case['reference_scope'],**r) for r in rows)
        if 'legacy_reference' in case:
            values={f['key']:f['value'] for f in result.get('fields',[])}
            legacy_rows=[dict(case_id=case['id'],**r) for r in score(case['legacy_reference'],values,case['legacy_fields']) if r['reference_status']=='present']
            if not saved.exists():
                for row in legacy_rows:row['outcome']='not_run'
            legacy.extend(legacy_rows)
    probe.csv_file(out/'accuracy_fields.csv',fields);probe.csv_file(out/'legacy_present39.csv',legacy)
    groups={'diploma':[r for r in fields if r['doc_type']=='DIPLOMA'],'degree_control':[r for r in fields if r['doc_type']=='DEGREE_CERT'],
            'date_roles':[r for r in fields if r['doc_type']=='DIPLOMA' and r['field'] in {'enroll_date','graduate_date','issue_date'}],
            'legacy_present39':legacy,'all':fields}
    scores={}
    for name,rows in groups.items():
        counts=Counter(r['outcome'] for r in rows);total=sum(r['reference_status']=='present' for r in rows)
        scores[name]=dict(present=total,correct=counts['correct'],accuracy=counts['correct']/total if total and not counts['not_run'] else None,
            missing=counts['missing'],wrong=counts['wrong'],not_run=counts['not_run'],correct_absence=counts['correct_absence'],false_positive=counts['false_positive'])
    probe.save(out/'accuracy_summary.json',dict(scores=scores,planned_cases=len(cases),measured_cases=len(tasks),reference_counts=protocol['certificate_references']))
    return scores

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--port',type=int,default=8783);args=parser.parse_args()
    out=probe.isolated_output(args.output,new=args.prepare)
    if args.prepare:
        protocol=freeze(out,json.load(sys.stdin));print(json.dumps(dict(status='prepared',cases=len(protocol['cases']),references=protocol['certificate_references'])))
        return 0
    probe.prepare=prepared
    status=probe.run(out,args.port,mode='single_resident')
    print(json.dumps(dict(accuracy=summarize(out)),ensure_ascii=False))
    return status

if __name__=='__main__':sys.exit(main())
