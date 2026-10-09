"""Isolated serial real-sample probe; public metrics contain no personal values."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import msvcrt
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from PIL import Image
from ocr_app.business import prepare_uploads
from ocr_app.client import RuntimeClient
from ocr_app.config import RuntimeConfig
from ocr_app.pipeline import process_document
from ocr_app.storage import Storage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def probe(out, source_dir, prepare_only=False, native_only=False):
    out = out.resolve()
    if not out.is_relative_to(ROOT / 'output') or out == ROOT / 'output':
        raise ValueError('OUTPUT_NOT_ISOLATED')
    out.mkdir(parents=True, exist_ok=False)
    vault = Storage(out / 'private/data')
    cases = []
    # Manually selected number rows after local visual inspection. No full card
    # image or incoming metadata is copied to this new probe's storage.
    crops = [('bank-001-p1', 'bankcard-baseline', (150, 885, 945, 970)),
             ('bank-002-p1', 'bankcard-crop', (140, 422, 1035, 503)),
             ('bank-003-p1', 'bankcard-baseline', (145, 550, 1470, 668))]
    references = json.loads((ROOT / 'output/bankcard-baseline/review-reference.json').read_text(encoding='utf-8-sig'))
    gold = {entry['id']: entry['card_number'].replace(' ', '') for entry in references['samples']}
    for identifier, folder, bbox in crops:
        path = ROOT / 'output' / folder / 'inputs' / f'{identifier}.png'
        original = path.read_bytes()
        with Image.open(io.BytesIO(original)) as image:
            buffer = io.BytesIO()
            image.crop(bbox).convert('RGB').save(buffer, format='PNG')
        data = buffer.getvalue()
        cases.append(dict(id=identifier, doc_type='BANK_CARD', ref=vault.put(data),
                          input_sha256=digest(data), source_sha256=digest(original), manual_roi=list(bbox),
                          reference_number=gold[identifier]))
    for index, path in enumerate(sorted(source_dir.iterdir()), 1):
        if path.is_file() and path.suffix.lower() in {'.pdf', '.jpg', '.jpeg', '.png'}:
            data = path.read_bytes()
            cases.append(dict(id=f'xuexin-{index:03d}', doc_type='XUEXIN_DIPLOMA_TABLE',
                              ref=vault.put(data), input_sha256=digest(data), source_path=str(path)))
    vault.put(json.dumps(cases, ensure_ascii=False).encode())
    if native_only:
        cases = [case for case in cases if case.get('source_path', '').lower().endswith('.pdf')]
    protocol = dict(mode='single_resident', execution='serial', cases=[
        {key: value for key, value in case.items() if key not in {'ref', 'reference_number', 'source_path'}} for case in cases],
        bank_reference_status=references.get('status'), manual_roi=True,
        limitations=['manual number crops are not automatic region detection',
                     'Xuexin filled-field count is not accuracy; no independent ground truth',
                     'one GLM model resident; not a production concurrency or Mac benchmark'])
    (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    if native_only:
        protocol.update(mode='cpu_native_only', models=[])
    if prepare_only:
        print(json.dumps(dict(status='prepared', cases=len(cases))), flush=True)
        return
    rows = []
    runtime = None
    with (contextlib.nullcontext() if native_only else (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')) as lease:
        if lease is not None:
            if lease.tell() == 0:
                lease.write(b'1'); lease.flush()
            lease.seek(0)
            try:
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                protocol['status'] = 'NOT_STARTED_GPU_CHANNEL_BUSY'
                (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
                print(json.dumps(dict(status=protocol['status'])), flush=True)
                return
        try:
            if not native_only:
                runtime = RuntimeClient(RuntimeConfig(out / 'session', mode='single_resident'))
                started = time.monotonic()
                runtime.start()
                deadline = started + 180
                previous = None
                while runtime.snapshot().get('state') not in {'ready', 'degraded'}:
                    state = runtime.snapshot()
                    if state != previous:
                        print(json.dumps(dict(startup=state)), flush=True)
                        previous = state
                    if time.monotonic() > deadline or not runtime.is_alive():
                        raise RuntimeError('STARTUP_FAILED')
                    time.sleep(.2)
                state = runtime.snapshot()
                if state.get('models', {}).get('glm_ocr') != 'ready':
                    raise RuntimeError('GLM_UNAVAILABLE')
                protocol['startup_seconds'] = time.monotonic() - started
            for case in cases:
                data = vault.read(case['ref'])
                if digest(data) != case['input_sha256']:
                    raise ValueError('INPUT_CHANGED')
                predictions = []
                requests = []
                def save_page(index, encoded, width, height):
                    vault.put(encoded)
                    return str(uuid.uuid4())
                def recognize(model, image_base64, task='ocr', timeout=180, **options):
                    requests.append(model)
                    if runtime is None:
                        raise AssertionError('Native-only probe must never run OCR')
                    prediction = runtime.request('recognize', wait=timeout + 5, model=model,
                                                 image_base64=image_base64, task=task, timeout=timeout, **options)
                    predictions.append(prediction)
                    return prediction
                began = time.monotonic()
                row = dict(sample_id=case['id'], doc_type=case['doc_type'], input_sha256=case['input_sha256'])
                try:
                    options = {}
                    if case['doc_type'] == 'BANK_CARD':
                        prepared = prepare_uploads([(data, 'number.png')], 'BANK_CARD', runtime)[0]
                        options['bank_admission'] = prepared['admission']
                        data = prepared['data']
                        row['admission_seconds'] = prepared['admission']['elapsed_seconds']
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = process_document(data, case['doc_type'], recognize=recognize,
                            progress=lambda *args: None, save_page=save_page,
                            record_attempt=lambda *args: None, cancelled=lambda: False,
                            deadline=time.monotonic() + 180, options=options)
                    vault.put(json.dumps(dict(result=result, predictions=predictions), ensure_ascii=False).encode())
                    fields = result.get('fields', [])
                    row.update(status=result['status'], pages=len(result.get('pages', [])),
                               populated=sum(field.get('value') not in (None, '') for field in fields),
                               fields=len(fields), pipeline_model_calls=len(predictions),
                               declined_native_ocr_requests=len(requests) if native_only else 0,
                               incomplete=sum(region.get('status') != 'recognized' for page in result.get('pages', []) for region in page.get('regions', [])))
                    if case['doc_type'] == 'BANK_CARD':
                        row['card_number_exact'] = next(f['value'] for f in fields if f['key'] == 'card_number') == case['reference_number']
                except Exception as error:
                    row.update(status='FAILED', error_code=getattr(error, 'code', 'PROBE_FAILED'))
                row['total_seconds'] = time.monotonic() - began
                rows.append(row)
                (out / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
                print(json.dumps(row), flush=True)
        finally:
            if runtime:
                runtime.close(graceful=False)
                protocol['process_tree_stopped'] = runtime.is_stopped()
                runtime.diag.close()
            (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
            if rows:
                keys = list(dict.fromkeys(key for row in rows for key in row))
                with (out / 'chart_data.csv').open('w', newline='', encoding='utf-8-sig') as target:
                    writer = csv.DictWriter(target, fieldnames=keys)
                    writer.writeheader(); writer.writerows(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--native-only', action='store_true')
    args = parser.parse_args()
    probe(args.output, args.source_dir, args.prepare_only, args.native_only)
