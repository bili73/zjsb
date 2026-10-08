"""Freeze paired inputs and references for the RAM-upgrade retest."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    out = ROOT / 'output' / ('two-model-retest-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    (out / 'inputs').mkdir(parents=True, exist_ok=False)
    baseline = []
    for batch in ['benchmark-rerun-20260929', 'medical-expansion-20260929']:
        for row in read(ROOT / 'output' / batch / 'inputs/manifest.json'):
            image = Path(row['image'])
            digest = sha(image)
            assert not row.get('input_sha256') or row['input_sha256'] == digest
            baseline.append({**row, 'parent_id':row['id'], 'variant':'baseline', 'repeat':1,
                'group':row.get('page_kind', row['group']), 'input_sha256':digest})
    regions = read(ROOT / 'output/paddle-ablation-20260929/inputs/crops-manifest.json')
    # Replace both old cert-026 regions with the final four-region refinement.
    regions = [row for row in regions if row['parent_id'] != 'cert-026-p1']
    regions += read(ROOT / 'output/paddle-ablation-20260929/refinement/inputs/manifest.json')
    by_parent = {row['parent_id']:row for row in baseline}
    enhanced = []
    for row in regions:
        image=Path(row['image'])
        digest=sha(image)
        assert digest == row['input_sha256']
        enhanced.append({**row,'variant':'enhanced','repeat':1,
            'group':by_parent[row['parent_id']]['group'], 'input_sha256':digest})
    manifest = baseline + enhanced
    anchors = ['cert-001-p1','bank-001-p1','medical-01-blood-p13']
    for repeat in [2,3]:
        for sid in anchors:
            manifest.append({**by_parent[sid], 'id':f'{sid}--repeat-{repeat}', 'repeat':repeat})
    assert len(manifest)==41 and len({r['id'] for r in manifest})==41
    (out/'inputs/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    references={}
    paths=['output/certificate-batch/review-reference.json','output/bankcard-baseline/review-reference.json',
           'output/benchmark-rerun-20260929/medical-reference.json','output/medical-expansion-20260929/references.json',
           'output/paddle-ablation-20260929/references.json']
    for index,rel in enumerate(paths):
        d=read(ROOT/rel)
        if index==0:
            for s in d['samples']: references[s['id']]={'fields':s['checks'],'normalization':'whitespace_only','source':rel}
        elif index==1:
            for s in d['samples']:
                r={'fields':{'卡号':s['card_number']},'normalization':'whitespace_only','source':rel}
                references[s['id']]=r
                if 'crop-'+s['id'] in by_parent: references['crop-'+s['id']]=r
        elif index==2:
            references[d['sample_id']]={'fields':d['checks'],'normalization':'nfkc_whitespace_only','source':rel}
        else:
            for sid,s in d['samples'].items():
                references[sid]={'fields':s['fields'],'normalization':s.get('normalization','nfkc_whitespace_only'),'source':rel}
    frozen={'status':'provisional_visual_not_human_double_reviewed','samples':references,
        'source_sha256':{p:sha(ROOT/p) for p in paths}}
    (out/'references.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    protocol={'created_at':datetime.now().astimezone().isoformat(),'models':['glm-ocr','paddleocr-vl'],
        'precision':'BF16','max_new_tokens':4096,'do_sample':False,'gpu_concurrency':1,
        'baseline_inputs':23,'baseline_unique_sources_note':'crop-bank-002-p1 is a diagnostic variant, not an independent card',
        'enhanced_parents':7,'enhanced_regions':12,'requests_per_model':41,'warmups_per_model':1,
        'repeat_anchors':anchors,'anchor_repeats':3,'generation_deadline_seconds':180,
        'repetition_stop':'identical contiguous 48-token block repeated four times; check every 32 generated tokens after 192',
        'enhanced_inputs':'frozen assistant-selected semantic crops plus rotation and cert-026 final refinement; NOT automatic layout',
        'timing':'record all failed and truncated costs; recognition includes processor+transfer+generation; request includes image IO/decode/output writing; model load separate',
        'end_to_end':'not measured: cached image preparation/manual region selection is not included; never label recognition as production end-to-end',
        'memory':'process RSS and machine used/available RAM sampled every 0.25s; torch peak allocated/reserved GPU; samples may miss short peaks',
        'comparison':'paired same-input model comparison plus paired enhanced-parent comparison, reference denominator fixed including missing fields',
        'recovery':'new attempt directory required if process interrupted; do not overwrite completed runs',
        'accuracy':'review actual current outputs with field-to-label assignment; no substring-only scoring or inherited previous predictions',
        'warmup':'first baseline certificate, unscored and excluded from normal timing'}
    (out/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(out))

if __name__=='__main__': main()
