"""Serial installed-model qualification on explicit regions, not automatic layout accuracy.

Input coordinates are normalized x0,y0,x1,y1. OCR and pixels stay encrypted.
Stop the idle application before running; this script never reads production data.
"""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from probe_photo_tables import require_idle, png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--region', action='append', help='role:x0,y0,x1,y1')
    parser.add_argument('--pipeline', action='store_true', help='Run the automatic bank-family pipeline on a file or directory')
    parser.add_argument('--doc-type', choices=('BANK_CARD', 'BANK_CARD_COPY'), default='BANK_CARD')
    args = parser.parse_args()
    if args.pipeline:return pipeline_probe(args, doc_type=args.doc_type)
    if not args.region:parser.error('--region or --pipeline is required')
    require_idle()
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(args.out.resolve() / 'diagnostics')
    from PIL import Image, ImageOps
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.storage import Storage
    import msvcrt
    content = args.source.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    with Image.open(args.source) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
    regions = []
    for entry in args.region:
        role, coords = entry.split(':')
        coords = [float(value) for value in coords.split(',')]
        assert len(coords) == 4 and 0 <= coords[0] < coords[2] <= 1 and 0 <= coords[1] < coords[3] <= 1
        crop = image.crop(tuple(round(value * (image.width if i % 2 == 0 else image.height)) for i, value in enumerate(coords)))
        crop.thumbnail((1600, 1600))
        regions.append((role, coords, png(crop)))
    vault = Storage(args.out / 'private/data')
    rows, results = [], []
    summary = dict(residency='single_resident', execution='serial', layout='manual_qualification', input_sha256=sha)
    runtime = None
    lock = (ROOT/'output/two-model-retest-gpu.lock').open('a+b')

    def save():
        (args.out/'private/results.enc').write_bytes(vault.pack(results))
        (args.out/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        if rows:
            with (args.out/'cases.csv').open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    try:
        if not lock.tell():lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        require_idle()
        runtime = RuntimeClient(RuntimeConfig(args.out/'session', mode='single_resident'))
        started = time.monotonic();runtime.start()
        while runtime.snapshot()['state'] == 'starting' and time.monotonic()-started < 260:time.sleep(.2)
        summary['startup_seconds'] = time.monotonic()-started
        if runtime.snapshot()['state'] != 'ready':raise RuntimeError('RUNTIME_NOT_READY')
        for model in ['glm_ocr', 'paddleocr_vl']:
            for role, coords, payload in regions:
                started = time.monotonic();prediction = {};error = None
                try:
                    prediction = runtime.request('recognize', wait=185, model=model,
                        image_base64=base64.b64encode(payload).decode('ascii'), task='ocr',
                        timeout=180, max_new_tokens=4096, generation_timeout_seconds=40.)
                except Exception as exc:error = getattr(exc, 'code', type(exc).__name__)
                row = dict(model=model, region=role, call_seconds=time.monotonic()-started,
                    recognition_seconds=prediction.get('recognition_seconds'), termination=prediction.get('termination_reason'),
                    output_tokens=prediction.get('output_tokens'), error_code=error)
                rows.append(row)
                results.append(dict(metrics=row, bbox=coords, image_ref=vault.put(payload), prediction=prediction))
                summary['statistics'] = runtime.request('statistics', wait=5)
                assert len(summary['statistics']['model_pids']) <= 1
                save();print(json.dumps(row), flush=True)
    finally:
        if runtime:runtime.close();summary['runtime_stopped'] = runtime.is_stopped()
        lock.close()
        summary['inputs_unchanged'] = hashlib.sha256(args.source.read_bytes()).hexdigest() == sha
        save()


def pipeline_probe(args, doc_type='BANK_CARD'):
    from uuid import uuid4
    import msvcrt
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.pipeline import process_document
    from ocr_app.storage import Storage
    require_idle()
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(args.out.resolve()/'diagnostics')
    paths = sorted(p for p in args.source.iterdir() if p.suffix.lower() in {'.jpg','.jpeg','.png'}) if args.source.is_dir() else [args.source]
    watched = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    code_hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),*(ROOT/'backend/ocr_app').glob('*.py'),ROOT/'backend/model_worker.py']}
    vault = Storage(args.out/'private/data')
    runtime = None;results = [];rows = []
    summary = dict(execution='serial',residency='single_resident',layout='automatic_pipeline',doc_type=doc_type,code_hashes=code_hashes)
    lock=(ROOT/'output/two-model-retest-gpu.lock').open('a+b')
    def save():
        (args.out/'private/results.enc').write_bytes(vault.pack(results))
        (args.out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        if rows:
            with (args.out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    try:
        if not lock.tell():lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);require_idle()
        runtime=RuntimeClient(RuntimeConfig(args.out/'session',mode='single_resident'))
        started=time.monotonic();runtime.start()
        while runtime.snapshot()['state']=='starting' and time.monotonic()-started<260:time.sleep(.2)
        summary['startup_seconds']=time.monotonic()-started
        if runtime.snapshot()['state']!='ready':raise RuntimeError('RUNTIME_NOT_READY')
        for index,path in enumerate(paths,1):
            attempts=[];pages=[];started=time.monotonic()
            def save_page(page,data,width,height):
                page_id=str(uuid4());pages.append(dict(page_id=page_id,ref=vault.put(data),width=width,height=height));return page_id
            def recognize(model,image,task,timeout,**extra):
                result=runtime.request('recognize',wait=timeout+5,model=model,image_base64=image,task=task,timeout=timeout,
                    max_new_tokens=4096,**{k:v for k,v in extra.items() if k=='generation_timeout_seconds'})
                stats=runtime.request('statistics',wait=5)
                assert len(stats['model_pids'])<=1
                return result
            result=process_document(path.read_bytes(),doc_type,recognize=recognize,progress=lambda *a:None,
                save_page=save_page,record_attempt=attempts.append,cancelled=lambda:False,deadline=started+180)
            row=dict(sample=f'sample-{index:02}',input_sha256=watched[path],wall_seconds=time.monotonic()-started,
                status=result['status'],regions=sum(len(p['regions']) for p in result['pages']),calls=len(attempts),
                filled_fields=','.join(f['key'] for f in result['fields'] if f['value'] is not None),
                termination=','.join(a.get('prediction',{}).get('termination_reason','failed') for a in attempts),
                error_code=result.get('error',{}).get('code'))
            rows.append(row);results.append(dict(metrics=row,source=str(path),source_ref=vault.put(path.read_bytes()),result=result,pages=pages,attempts=attempts))
            save();print(json.dumps(row),flush=True)
        summary['statistics']=runtime.request('statistics',wait=5)
    finally:
        if runtime:runtime.close();summary['runtime_stopped']=runtime.is_stopped()
        lock.close()
        summary['inputs_unchanged']=all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in watched.items())
        summary['code_unchanged_during_probe']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h for name,h in code_hashes.items())
        save()


if __name__ == '__main__':main()
