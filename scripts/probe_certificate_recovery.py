"""One fresh certificate pipeline; serial single-resident models and encrypted evidence."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from probe_photo_tables import require_idle
from ocr_app.client import RuntimeClient
from ocr_app.config import RuntimeConfig
from ocr_app.extraction import extract_fields
from ocr_app.pipeline import process_document
from ocr_app.storage import Storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--doc-type', choices=['DIPLOMA', 'DEGREE_CERT'], default='DIPLOMA')
    args = parser.parse_args()
    require_idle()
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(args.out.resolve() / 'diagnostics')
    content = args.source.read_bytes()
    source_hash = hashlib.sha256(content).hexdigest()
    vault = Storage(args.out / 'private/data')
    (args.out / 'private/source.enc').write_bytes(vault.pack(dict(path=str(args.source.resolve()), sha256=source_hash)))
    attempts, saved_pages, inputs = [], [], []
    summary = dict(execution='serial', residency='single_resident', source_sha256=source_hash,
                   doc_type=args.doc_type, status='STARTING', code_hashes={})
    for name in ['backend/ocr_app/pipeline.py', 'backend/ocr_app/certificate_recovery.py',
                 'backend/runtime_worker.py', 'scripts/probe_certificate_recovery.py']:
        summary['code_hashes'][name] = hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    runtime = None
    result = None
    import msvcrt
    lock = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
    def save():
        (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.out / 'private/results.enc').write_bytes(vault.pack(dict(attempts=attempts, pages=saved_pages, inputs=inputs, result=result)))
    try:
        if not lock.tell():
            lock.write(b'1'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        require_idle()
        runtime = RuntimeClient(RuntimeConfig(args.out / 'session', mode='single_resident'))
        started = time.monotonic()
        runtime.start()
        while runtime.snapshot()['state'] == 'starting' and time.monotonic() - started < 320:
            time.sleep(.2)
        summary['startup_seconds'] = round(time.monotonic() - started, 3)
        if runtime.snapshot()['state'] != 'ready':
            raise RuntimeError('RUNTIME_NOT_READY')
        summary['status'] = 'RUNNING'
        save()
        def recognize(model, payload, task, timeout, **extra):
            image = base64.b64decode(payload)
            inputs.append(dict(model=model, image_ref=vault.put(image), sha256=hashlib.sha256(image).hexdigest()))
            print(json.dumps(dict(event='model_call', model=model, timeout=round(timeout, 3))), flush=True)
            value = runtime.request('recognize', wait=timeout + 10, model=model, task=task,
                image_base64=payload, timeout=timeout, max_new_tokens=4096,
                generation_timeout_seconds=extra.get('generation_timeout_seconds'))
            stats = runtime.request('statistics', wait=5)
            assert len(stats['model_pids']) <= 1
            summary['statistics'] = stats
            return value
        def record(attempt):
            attempts.append(attempt)
            save()
            print(json.dumps(dict(event='attempt', model=attempt['model'], status=attempt['status'],
                  seconds=round(attempt['elapsed_seconds'], 3), recovery_fields=attempt.get('recovery_fields', []),
                  termination=attempt.get('prediction', {}).get('termination_reason'))), flush=True)
        def save_page(index, png, width, height):
            identity = str(uuid4())
            saved_pages.append(dict(page_id=identity, page=index, image_ref=vault.put(png), width=width, height=height))
            return identity
        started = time.monotonic()
        result = process_document(content, args.doc_type, recognize=recognize, progress=lambda *a: None,
            save_page=save_page, record_attempt=record, cancelled=lambda: False, deadline=started + 180)
        summary['pipeline_seconds'] = round(time.monotonic() - started, 3)
        primary = [dict(text=a['prediction']['text'], page=a['page_index'], region_id=a['region_id'],
                   extraction_method='ocr', bbox=a['bbox']) for a in attempts
                   if not a.get('recovery_fields') and a['status'] == 'completed']
        before = {f['key']: f.get('value') for f in extract_fields(primary, args.doc_type)}
        after = {f['key']: f.get('value') for f in result['fields']}
        summary.update(status=result['status'], primary_missing=[k for k, v in before.items() if v is None],
            recovered_fields=[k for k, v in before.items() if v is None and after.get(k) is not None],
            changed_filled_primary_fields=[k for k, v in before.items() if v is not None and after.get(k) != v],
            recovery_attempts=sum(bool(a.get('recovery_fields')) for a in attempts),
            remaining_required=[f['key'] for f in result['fields'] if f['required'] and not f.get('value')],
            primary_major=before.get('major'), final_major=after.get('major'),
            attempts=[{k:a.get(k) for k in ['model','status','elapsed_seconds','bbox','input_sha256','recovery_fields']}
                      | dict(termination=a.get('prediction', {}).get('termination_reason')) for a in attempts])
        assert not summary['changed_filled_primary_fields']
        assert summary['recovery_attempts'] <= 1
        save()
    except BaseException as error:
        summary.update(probe_failed=type(error).__name__)
        save()
        raise
    finally:
        if runtime:
            runtime.close()
            summary['runtime_stopped'] = runtime.is_stopped()
        lock.close()
        summary['source_unchanged'] = hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
        save()
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
