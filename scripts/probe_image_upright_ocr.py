"""Serial single-resident GLM comparison of before/after certificate preparation."""
import argparse
import base64
from collections import Counter
import csv
import io
import json
import msvcrt
from pathlib import Path
import sqlite3
import statistics
import sys
import time

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.config import RuntimeConfig
from ocr_app.extraction import extract_fields
from ocr_app.image_preprocessing import prepare_image
from ocr_app.runtime import ModelManager
from ocr_app.storage import Storage
from probe_current_pipeline import frozen, read_only_storage, digest
from schema_extraction import normalize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    vault = Storage(args.out / 'private/data')
    source = ROOT / 'output/dual-extraction-20260930-v1'
    protocol, storage, fixture = frozen(source)
    watched = {p:digest(p.read_bytes()) for p in [source/'protocol.json',source/'private/fixture.enc']}
    samples = []
    for item in fixture['samples']:
        if item['doc_type'] not in {'DIPLOMA','DEGREE_CERT'}:
            continue
        image_bytes = storage.read(item['image_ref'])
        assert digest(image_bytes)==item['input_sha256']
        watched[storage.path(item['image_ref'])]=digest(storage.path(item['image_ref']).read_bytes())
        date_key = 'award_date' if item['doc_type']=='DEGREE_CERT' else 'issue_date'
        reference={key:item['reference'][key]['value'] for key in ['school_name',date_key]}
        image=ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert('RGB')
        if item['id']=='cert-007-p1':
            image=image.transpose(Image.Transpose.ROTATE_90)  # Manually verified sideways source.
        samples.append(dict(id=item['id'],kind=item['doc_type'],image=image,reference=reference))
    production = read_only_storage(ROOT/'.runtime/data')
    connection=sqlite3.connect((ROOT/'.runtime/data/tasks.sqlite3').as_uri()+'?mode=ro',uri=True)
    task_id='5edd1575-49c9-48a7-8d64-0379bae7f698'
    reference,result_cipher,revision=connection.execute('SELECT input_ref,result_enc,revision FROM tasks WHERE id=?',(task_id,)).fetchone()
    original=production.read(reference)
    original_hash=digest(original)
    samples.append(dict(id='degree-observed',kind='DEGREE_CERT',
        image=ImageOps.exif_transpose(Image.open(io.BytesIO(original))).convert('RGB'),
        reference={'school_name':'岭南师范学院','award_date':'2025-06-19'}))
    code_paths=[Path(__file__), ROOT/'backend/ocr_app/image_preprocessing.py',ROOT/'backend/ocr_app/extraction.py']
    code_hashes={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in code_paths}
    rows=[];private=[];startup=None
    manager=None
    lease=(ROOT/'output/two-model-retest-gpu.lock').open('a+b')
    try:
        if lease.tell()==0:
            lease.write(b'1');lease.flush()
        lease.seek(0)
        msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
        manager=ModelManager(RuntimeConfig(args.out/'session',mode='single_resident'))
        began=time.monotonic();manager.start();startup=time.monotonic()-began
        assert set(manager.clients)=={'glm_ocr'} and manager.view['models']['glm_ocr']=='ready'
        for sample in samples:
            for angle in [0,90,180,5]:
                image=sample['image']
                if angle in {90,180}:
                    varied=image.transpose({90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180}[angle])
                else:
                    varied=image if angle==0 else image.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True,fillcolor='white')
                corrected,decision=prepare_image(varied)
                case=f'{sample["id"]}-{angle:03}'
                for variant,pixels in [('before',varied),('after',corrected)]:
                    pixels=pixels.copy();pixels.thumbnail((1600,1600))
                    stream=io.BytesIO();pixels.save(stream,format='PNG');png=stream.getvalue()
                    began=time.monotonic();prediction={};error=None
                    try:
                        assert set(manager.clients)=={'glm_ocr'}
                        prediction=manager.recognize('glm_ocr',image_base64=base64.b64encode(png).decode('ascii'),task='ocr',timeout=180,max_new_tokens=4096)
                    except Exception as exc:
                        error=getattr(exc,'code','PROBE_RECOGNITION_FAILED')
                    elapsed=time.monotonic()-began
                    termination=prediction.get('termination_reason')
                    values={}
                    if not error and termination=='eos':
                        values={f['key']:f['value'] for f in extract_fields([dict(text=prediction['text'],page=1,extraction_method='ocr')],sample['kind'])}
                    outcomes={key:'missing' if values.get(key) is None else 'correct' if normalize(key,values[key])==normalize(key,expected) else 'wrong' for key,expected in sample['reference'].items()}
                    rows.append(dict(case=case,doc_type=sample['kind'],added_rotation_ccw=angle,variant=variant,
                        elapsed_seconds=elapsed,recognition_seconds=prediction.get('recognition_seconds'),
                        input_sha256=digest(png),termination=termination,error_code=error,
                        school_outcome=outcomes['school_name'],date_outcome=next(v for k,v in outcomes.items() if k!='school_name'),
                        preparation_seconds=decision['elapsed_seconds'] if variant=='after' else 0.,
                        rotation_degrees=decision['rotation_degrees'] if variant=='after' else 0,
                        deskew_degrees=decision['deskew_degrees'] if variant=='after' else 0.))
                    private.append(dict(case=case,variant=variant,prediction=prediction,reference=sample['reference'],decision=decision))
                    (args.out/'private/results.enc').write_bytes(vault.pack(private))
                    with (args.out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                    print(f'{len(rows)}/40 {case} {variant}: school={outcomes["school_name"]}, date={next(v for k,v in outcomes.items() if k!="school_name")}, {elapsed:.2f}s',flush=True)
    finally:
        if manager is not None:manager.close()
        lease.close()
    assert all(digest(p.read_bytes())==h for p,h in watched.items())
    assert digest(production.read(reference))==original_hash
    assert connection.execute('SELECT result_enc,revision FROM tasks WHERE id=?',(task_id,)).fetchone()==(result_cipher,revision)
    assert all(digest((ROOT/name).read_bytes())==h for name,h in code_hashes.items())
    summary=dict(residency='single_resident',recognition_model='glm_ocr',execution='serial',sources=len(samples),
        cases=len(rows)//2,recognition_calls=len(rows),startup_seconds=startup,originals_and_saved_results_unchanged=True,
        limitations='Five overlapping existing documents, synthetically rotated; two target fields per case with provisional historical/agent-reviewed references. This is a paired preparation experiment, not held-out/full-document accuracy or production throughput. Timings exclude preparation unless separately stated; loading/warmup is separate. All failed/truncated calls remain in the denominator.',
        code_hashes=code_hashes)
    for variant in ['before','after']:
        selected=[r for r in rows if r['variant']==variant]
        summary[variant]=dict(target_fields=len(selected)*2,outcomes=dict(Counter(r[k] for r in selected for k in ['school_outcome','date_outcome'])),
            mean_recognition_call_seconds=statistics.mean(r['elapsed_seconds'] for r in selected),
            failures=sum(bool(r['error_code']) or r['termination']!='eos' for r in selected),
            by_rotation={str(angle):dict(Counter(r[k] for r in selected if r['added_rotation_ccw']==angle for k in ['school_outcome','date_outcome'])) for angle in [0,90,180,5]})
    with (args.out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
