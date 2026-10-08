"""Aggregate current paired measurements and explicitly reviewed predictions."""
import argparse
import csv
import hashlib
import json
import re
import statistics
import unicodedata
from pathlib import Path

MODELS=['glm-ocr','paddleocr-vl']

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(v,rule):
    v=str(v)
    if 'nfkc' in rule.lower(): v=unicodedata.normalize('NFKC',v)
    return re.sub(r'\s+','',v)

def write_csv(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

def score(rows):
    total=len(rows)
    reviewed=sum(r['reviewed'] for r in rows)
    correct=sum(r['exact_match'] or 0 for r in rows)
    return dict(field_correct=correct if reviewed else None,field_total=total,field_reviewed=reviewed,
        field_accuracy=correct/total if total and reviewed==total else None)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-dir',type=Path,required=True)
    args=ap.parse_args()
    base=args.run_dir.resolve()
    manifest=read(base/'inputs/manifest.json')
    refs=read(base/'references.json')['samples']
    out=base/'data'
    out.mkdir(exist_ok=True)
    reviews={}
    for p in sorted((base/'reviews').glob('*.json')):
        d=read(p)
        for variant,parents in d['variants'].items():
            for sid,review in parents.items():
                key=(d['model'],variant,sid)
                assert key not in reviews,key
                for filename,digest in review.get('output_sha256',{}).items():
                    assert sha(base/d['model']/Path(filename).name).lower()==digest.lower(),(p,filename)
                reviews[key]={**review,'review_file':p.relative_to(base).as_posix()}
    runs=[]
    by_key={}
    for model in MODELS:
        samples=[{**manifest[0],'id':'warmup-'+manifest[0]['id'],'phase':'warmup'}]+manifest
        for sample in samples:
            path=base/model/(sample['id']+'.metrics.json')
            row=dict(model=model,sample_id=sample['id'],parent_id=sample['parent_id'],variant=sample['variant'],
                group=sample['group'],repeat=sample['repeat'],phase=sample.get('phase','measurement'),input_sha256=sample['input_sha256'])
            assert sha(Path(sample['image']))==sample['input_sha256']
            if path.exists():
                m=read(path)
                textfile=path.with_name(sample['id']+'.txt')
                valid=textfile.exists() and hashlib.sha256(textfile.read_text(encoding='utf-8').encode('utf-8')).hexdigest()==m.get('output_sha256')
                row.update(status=m['status'],termination_reason=m['termination_reason'],output_valid=int(valid),
                    technical_success=int(m['status']=='ok' and m['termination_reason']=='eos' and valid),
                    token_limit=int(m.get('hit_token_limit',False)),repetition_stop=int(m['termination_reason']=='repetition_stop'),
                    timeout=int(m['termination_reason']=='generation_timeout'),
                    recognition_s=m.get('seconds'),request_s=m['request_wall_seconds'],generation_s=m.get('generation_seconds'),
                    output_tokens=m.get('output_tokens'),peak_gpu_allocated_gib=m['peak_allocated_gib'],
                    peak_gpu_reserved_gib=m['peak_reserved_gib'],peak_process_rss_gib=m['process_rss_peak_gib'],
                    peak_host_used_gib=m['host_used_peak_gib'],min_host_available_gib=m['host_available_min_gib'],
                    started_at=m['started_at'],finished_at=m['finished_at'],metrics_file=path.relative_to(base).as_posix())
            else:
                row.update(status='missing',technical_success=None,recognition_s=None,request_s=None)
            runs.append(row)
            if row['phase']=='measurement' and row['repeat']==1:
                by_key.setdefault((model,row['variant'],row['parent_id']),[]).append(row)
    fields=[]
    pages=[]
    for key,requests in by_key.items():
        model,variant,sid=key
        review=reviews.get(key,{})
        reference=refs.get(sid,{'fields':{},'normalization':'whitespace_only','source':None})
        predictions=review.get('fields',{})
        checks=[]
        for name,expected in reference['fields'].items():
            reviewed=bool(review.get('complete_reviewed') and name in predictions)
            predicted=predictions.get(name)
            exact=int(predicted is not None and norm(predicted,reference['normalization'])==norm(expected,reference['normalization'])) if reviewed else None
            item=dict(model=model,variant=variant,parent_id=sid,group=requests[0]['group'],field=name,
                reference_value=expected,predicted_value=predicted,reviewed=int(reviewed),exact_match=exact,
                normalization=reference['normalization']+'; punctuation preserved',reference_status='provisional_not_human_double_reviewed',
                reference_source=reference['source'],review_file=review.get('review_file'))
            checks.append(item)
        fields.extend(checks)
        have_all=all(r['status']!='missing' for r in requests)
        technical=all(r.get('technical_success') for r in requests) if have_all else None
        reviewed_complete=bool(review.get('complete_reviewed'))
        complete=int(technical and not review.get('degenerate_repetition')) if have_all and reviewed_complete else None
        page=dict(model=model,variant=variant,parent_id=sid,group=requests[0]['group'],regions=len(requests),
            complete_no_limit_or_repetition=complete,technical_success=int(technical) if technical is not None else None,
            review_complete=int(reviewed_complete),recognition_s=sum(r['recognition_s'] for r in requests) if all(r.get('recognition_s') is not None for r in requests) else None,
            request_s=sum(r['request_s'] for r in requests) if all(r.get('request_s') is not None for r in requests) else None,
            token_limit_regions=sum(r.get('token_limit',0) for r in requests),repetition_stop_regions=sum(r.get('repetition_stop',0) for r in requests),
            timeout_regions=sum(r.get('timeout',0) for r in requests),notes=review.get('notes'),**score(checks))
        for metric in ['peak_gpu_allocated_gib','peak_gpu_reserved_gib','peak_process_rss_gib','peak_host_used_gib']:
            values=[r[metric] for r in requests if metric in r]
            page[metric]=max(values) if values else None
        pages.append(page)
    lookup={(p['model'],p['variant'],p['parent_id']):p for p in pages}
    for r in runs:
        if r['phase']=='measurement' and r['repeat']==1 and r['variant']=='baseline':
            p=lookup[(r['model'],r['variant'],r['parent_id'])]
            r.update(score_scope='selected_parent_fields',**{k:p[k] for k in ['field_correct','field_total','field_reviewed','field_accuracy']})
        else:
            r.update(score_scope='parent_aggregate_in_pages' if r['variant']=='enhanced' else 'timing_only',
                field_correct=None,field_total=None,field_reviewed=None,field_accuracy=None)
    for p in pages:
        p['paired_complete']=int(all(lookup.get((model,p['variant'],p['parent_id']),{}).get('complete_no_limit_or_repetition')==1 for model in MODELS))
    summaries=[]
    enhanced_parents={p['parent_id'] for p in pages if p['variant']=='enhanced'}
    for variant in ['baseline','enhanced']:
        groups=sorted({p['group'] for p in pages if p['variant']==variant})
        for group in groups+['all_primary_inputs']:
            for model in MODELS:
                selected=[p for p in pages if p['model']==model and p['variant']==variant and (p['group']==group or (group=='all_primary_inputs' and p['group']!='bankcard_crop'))]
                if not selected: continue
                keys={p['parent_id'] for p in selected}
                checks=[f for f in fields if f['model']==model and f['variant']==variant and f['parent_id'] in keys]
                comparable=[p['recognition_s'] for p in selected if p['paired_complete'] and p['recognition_s'] is not None]
                summaries.append(dict(model=model,variant=variant,group=group,planned=len(selected),
                    completed=sum(p['complete_no_limit_or_repetition']==1 for p in selected),
                    unreviewed=sum(not p['review_complete'] for p in selected),paired_complete=len(comparable),
                    paired_mean_s=statistics.mean(comparable) if comparable else None,
                    paired_median_s=statistics.median(comparable) if comparable else None,
                    all_request_sum_s=sum(p['request_s'] for p in selected) if all(p['request_s'] is not None for p in selected) else None,
                    token_limit_regions=sum(p['token_limit_regions'] for p in selected),
                    repetition_stop_regions=sum(p['repetition_stop_regions'] for p in selected),
                    timeout_regions=sum(p['timeout_regions'] for p in selected),**score(checks)))
    paired=[]
    for sid in sorted(enhanced_parents):
        for model in MODELS:
            for variant in ['baseline','enhanced']:
                paired.append(lookup[(model,variant,sid)])
    anchor_stats=[]
    for sid in read(base/'protocol.json')['repeat_anchors']:
        common={r['repeat'] for r in runs if r['model']==MODELS[0] and r['parent_id']==sid and r['phase']=='measurement' and r['variant']=='baseline' and r.get('technical_success')}
        common &= {r['repeat'] for r in runs if r['model']==MODELS[1] and r['parent_id']==sid and r['phase']=='measurement' and r['variant']=='baseline' and r.get('technical_success')}
        for model in MODELS:
            values=[r['recognition_s'] for r in runs if r['model']==model and r['parent_id']==sid and r['phase']=='measurement' and r['variant']=='baseline' and r['repeat'] in common]
            anchor_stats.append(dict(model=model,parent_id=sid,paired_repeats=len(values),mean_s=statistics.mean(values) if values else None,median_s=statistics.median(values) if values else None,stdev_s=statistics.stdev(values) if len(values)>1 else None,min_s=min(values) if values else None,max_s=max(values) if values else None))
    resources=[]
    for model in MODELS:
        sp=base/model/'session.json'
        if not sp.exists(): continue
        s=read(sp)
        rows=[r for r in runs if r['model']==model and r['status']!='missing']
        resources.append(dict(model=model,status=s.get('status','running'),model_load_s=s['load_seconds'],
            session_wall_s=s.get('session_wall_seconds'),gpu=s['gpu'],host_total_gib=s['host_total_gib'],
            load_peak_rss_gib=s['load_memory']['process_rss_peak_gib'],
            process_rss_peak_gib=max([r['peak_process_rss_gib'] for r in rows]+[s['load_memory']['process_rss_peak_gib']]),
            gpu_allocated_peak_gib=max([r['peak_gpu_allocated_gib'] for r in rows]+[s['load_peak_allocated_gib']]),
            gpu_reserved_peak_gib=max([r['peak_gpu_reserved_gib'] for r in rows]+[s['load_peak_reserved_gib']]),
            host_used_peak_gib=max([r['peak_host_used_gib'] for r in rows]+[s['load_memory']['host_used_peak_gib']]),
            host_available_min_gib=min([r['min_host_available_gib'] for r in rows]+[s['load_memory']['host_available_min_gib']]),
            model_revision=s['revision'],sleep_prevention=s['sleep_prevention_active']))
    diagnostic=[]
    dp=base/'glm-header-prompt-check/review.json'
    if dp.exists():
        d=read(dp)
        sid=d['parent_id']
        ref=refs[sid]
        for filename,digest in d['output_sha256'].items():
            assert sha(dp.parent/'glm-ocr'/filename).lower()==digest.lower()
        assert set(d['fields'])==set(ref['fields'])
        correct=sum(d['fields'][k] is not None and norm(d['fields'][k],ref['normalization'])==norm(v,ref['normalization']) for k,v in ref['fields'].items())
        m=read(dp.parent/'glm-ocr'/(d['request_id']+'.metrics.json'))
        p=lookup[('glm-ocr','baseline',sid)]
        for prompt,seconds,request,good,total in [('Table Recognition:',p['recognition_s'],p['request_s'],p['field_correct'],p['field_total']),('Text Recognition:',m['seconds'],m['request_wall_seconds'],correct,len(ref['fields']))]:
            diagnostic.append(dict(model='glm-ocr',parent_id=sid,prompt=prompt,recognition_s=seconds,request_s=request,field_correct=good,field_total=total,field_accuracy=good/total if good is not None else None,scope='single_page_prompt_diagnostic_not_main_aggregate',notes=d['notes']))
    datasets=dict(runs=runs,pages=pages,fields=fields,summary=summaries,paired_intervention=paired,repeated_timing=anchor_stats,resources=resources,prompt_diagnostic=diagnostic)
    for name,rows in datasets.items(): write_csv(out/(name+'.csv'),rows)
    audit=dict(missing_metrics=[r['sample_id']+':'+r['model'] for r in runs if r['status']=='missing'],
        unreviewed_pages=[p['model']+':'+p['variant']+':'+p['parent_id'] for p in pages if not p['review_complete']],
        references_sha256=sha(base/'references.json'),manifest_sha256=sha(base/'inputs/manifest.json'),
        normalization='NFKC only when specified, remove whitespace, preserve punctuation including decimals and signs',
        scope='single selected-field benchmark; references provisional; enhanced crops manually selected before retest; no inference from filename or previous outputs')
    (out/'benchmark.json').write_text(json.dumps({**datasets,'audit':audit},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(runs=len(runs),pages=len(pages),fields=len(fields),missing=len(audit['missing_metrics']),unreviewed=len(audit['unreviewed_pages']))))

if __name__=='__main__': main()
