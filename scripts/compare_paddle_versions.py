"""Serial old/new medical-table probe; private references never leave encrypted storage."""
import argparse
import base64
from collections import defaultdict
import ctypes
import json
import msvcrt
from pathlib import Path
import re
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.runtime import ModelProcess
from ocr_app.extraction import extract_medical_items
from compare_schema_extraction import csv_file, digest, save

CHECKPOINTS = ['paddleocr-vl', 'paddleocr-vl-1.6']
SOURCES = ['backend/model_worker.py', 'backend/ocr_app/extraction.py',
           'backend/ocr_app/table_format.py',
           'scripts/dual_model_worker.py', 'scripts/schema_model_worker.py',
           'scripts/compare_paddle_versions.py']


def norm(value):
    return re.sub(r'\s+', '', str(value))


def prepare(out, match_legacy_pixels=False):
    previous = ROOT / 'output/two-model-retest-20260929-152421'
    manifest = json.loads((previous / 'inputs/manifest.json').read_text(encoding='utf-8'))
    references = json.loads((previous / 'references.json').read_text(encoding='utf-8'))['samples']
    selected = ['medical-page-12', 'medical-01-blood-p13', 'medical-02-blood-p13']
    out.mkdir(parents=True, exist_ok=False)
    storage = Storage(out / 'private/data')
    samples = []
    for sid in selected:
        sample = next(s for s in manifest if s['id'] == sid)
        data = Path(sample['image']).read_bytes()
        if digest(data) != sample['input_sha256']:
            raise ValueError('SOURCE_IMAGE_CHANGED')
        refs = references[sid]['fields']
        refs = {k.removeprefix('血常规_'): v for k, v in refs.items()
                if sid == 'medical-page-12' or k.startswith('血常规_')}
        if len(refs) != 24:
            raise ValueError('REFERENCE_SCHEMA_CHANGED')
        samples.append(dict(id=sid, image_ref=storage.put(data), input_sha256=digest(data), reference=refs))
    encrypted = storage.pack(samples)
    (out / 'private/fixture.enc').write_bytes(encrypted)
    save(out / 'protocol.json', dict(prepared_at=time.time(), fixture_sha256=digest(encrypted),
         sources={p: digest((ROOT / p).read_bytes()) for p in SOURCES},
         checkpoints={k: json.loads((ROOT / 'models' / k / 'download_manifest.json').read_text()) for k in CHECKPOINTS},
         references_sha256=digest((previous / 'references.json').read_bytes()),
         repeats=2, max_new_tokens=4096, soft_budget_seconds=45, hard_timeout_seconds=65,
         match_legacy_pixels=match_legacy_pixels,
         scoring='Exact whitespace-normalized result_raw by item alias/name; 24 blood-result fields per page; not full report, units, intervals or abnormal-marker accuracy',
         references='Existing provisional visual references; not independently double-reviewed',
         samples=[{k: s[k] for k in ['id', 'input_sha256']} for s in samples]))


def run(out):
    protocol = json.loads((out / 'protocol.json').read_text())
    if (out / 'session.json').exists():
        raise ValueError('RUN_ALREADY_STARTED')
    for path, expected in protocol['sources'].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError('CODE_CHANGED')
    for checkpoint, expected in protocol['checkpoints'].items():
        if json.loads((ROOT / 'models' / checkpoint / 'download_manifest.json').read_text()) != expected:
            raise ValueError('MODEL_CHANGED')
    storage = Storage(out / 'private/data')
    encrypted = (out / 'private/fixture.enc').read_bytes()
    if digest(encrypted) != protocol['fixture_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    samples = storage.unpack(encrypted)
    lease = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
    if lease.tell() == 0:
        lease.write(b'1'); lease.flush()
    lease.seek(0)
    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    guard = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    session = dict(status='running', started_at=time.time(), models=[], in_flight=None, sleep_prevention_active=guard)
    requests, fields = [], []
    save(out / 'session.json', session)
    try:
        for checkpoint in CHECKPOINTS:
            cache = {}
            pixel_args = ['--match-legacy-pixels'] if checkpoint == 'paddleocr-vl-1.6' and protocol.get('match_legacy_pixels') else []
            config = SimpleNamespace(session_dir=out / 'technical' / checkpoint, model_command=lambda _: [
                str(ROOT / '.venvs' / checkpoint / 'Scripts/python.exe'), '-u', '-X', 'utf8',
                str(ROOT / 'scripts/dual_model_worker.py'), '--model', 'paddleocr-vl', '--checkpoint', checkpoint] + pixel_args)
            process = ModelProcess('paddleocr_vl', config, lambda key, state: print(json.dumps(dict(checkpoint=checkpoint, phase=state)), flush=True))
            loading = dict(checkpoint=checkpoint)
            session['models'].append(loading)
            try:
                begin = time.perf_counter()
                loading['metadata'] = process.call('load', 120)
                loading['load_request_seconds'] = time.perf_counter() - begin
                save(out / 'session.json', session)
                for sample in samples:
                    for repeat in range(1, protocol['repeats'] + 1):
                        data = storage.read(sample['image_ref'])
                        if digest(data) != sample['input_sha256']:
                            raise ValueError('INPUT_CHANGED')
                        session['in_flight'] = dict(checkpoint=checkpoint, sample_id=sample['id'], repeat=repeat)
                        save(out / 'session.json', session)
                        begin = time.perf_counter()
                        failure = None
                        task = sample.get('task', 'table')
                        key = (sample['input_sha256'], task)
                        cached = cache.get(key) if protocol.get('deduplicate') else None
                        if cached:
                            result, original_sample_id = cached
                        else:
                            original_sample_id = sample['id']
                            try:
                                result = process.call('recognize', protocol['hard_timeout_seconds'],
                                         image_base64=base64.b64encode(data).decode(), task=task,
                                         max_new_tokens=protocol['max_new_tokens'])
                            except Exception as error:
                                failure = error
                                result = dict(termination_reason='exception', error_code=getattr(error, 'code', type(error).__name__), text='')
                            if failure is None:
                                cache[key] = (result, original_sample_id)
                        items, limitations = extract_medical_items([dict(text=result['text'], page=1, extraction_method='ocr', bbox=[0, 0, 1, 1])])
                        candidates = defaultdict(list)
                        for item in items:
                            for key in {item['name'], item['alias']} - {None, ''}:
                                candidates[norm(key)].append(item['result_raw'])
                        values = {}
                        row = dict(checkpoint=checkpoint, sample_id=sample['id'], repeat=repeat, input_sha256=sample['input_sha256'],
                                   case=sample.get('case', 'blood_page'), task=task,
                                   executed_inference=not bool(cached), reused_from_sample_id=original_sample_id if cached else None,
                                   termination_reason=result['termination_reason'], error_code=result.get('error_code'),
                                   request_seconds=time.perf_counter() - begin if not cached else None,
                                   reuse_decode_seconds=time.perf_counter() - begin if cached else None,
                                   **{k: v for k, v in result.items() if k not in {'text', 'termination_reason', 'error_code'}})
                        current_fields = []
                        for basis, refs in [(sample.get('reference_basis', 'visual_provisional'), sample['reference']),
                                            ('visual_provisional', sample.get('visual_reference', {}))]:
                            for field_key, expected in refs.items():
                                options = set(candidates.get(norm(field_key), []))
                                predicted = next(iter(options)) if len(options) == 1 else None
                                values[field_key] = predicted
                                outcome = 'correct' if predicted is not None and norm(predicted) == norm(expected) else 'missing' if predicted is None else 'wrong'
                                current_fields.append(dict(checkpoint=checkpoint, sample_id=sample['id'], repeat=repeat, field=field_key,
                                                           reference_basis=basis, outcome=outcome, has_value=predicted is not None,
                                                           complete_generation=result['termination_reason'] == 'eos'))
                        fields.extend(current_fields)
                        row['prediction_ref'] = storage.put(json.dumps(dict(result=result, values=values, limitations=limitations), ensure_ascii=False).encode())
                        requests.append(row)
                        columns = list(dict.fromkeys(k for r in requests for k in r))
                        csv_file(out / 'requests.csv', [{k: r.get(k) for k in columns} for r in requests])
                        csv_file(out / 'fields.csv', fields)
                        print(json.dumps(dict(checkpoint=checkpoint, sample=sample['id'], repeat=repeat,
                                              seconds=round(row['request_seconds'], 3) if row['request_seconds'] is not None else None, termination=row['termination_reason'],
                                              reused=bool(cached), correct=sum(f['outcome'] == 'correct' for f in current_fields),
                                              scored_fields=len(current_fields))), flush=True)
                        if failure:
                            raise failure
            finally:
                process.close()
                loading['owned_process_exited'] = process.poll() is not None
                save(out / 'session.json', session)
        session.update(status='finished', in_flight=None)
    except Exception as error:
        session.update(status='failed', error_code=getattr(error, 'code', type(error).__name__))
    finally:
        session['finished_at'] = time.time()
        save(out / 'session.json', session)
        if guard:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lease.close()
    summary = []
    for checkpoint in CHECKPOINTS:
        measured = [r for r in requests if r['checkpoint'] == checkpoint]
        scored = [f for f in fields if f['checkpoint'] == checkpoint]
        executed = [r for r in measured if r['executed_inference']]
        if measured:
            summary.append(dict(checkpoint=checkpoint, requests=len(measured), fields=len(scored),
                                correct=sum(f['outcome'] == 'correct' for f in scored), missing=sum(f['outcome'] == 'missing' for f in scored),
                                wrong=sum(f['outcome'] == 'wrong' for f in scored),
                                executed_requests=len(executed), reused_requests=len(measured)-len(executed),
                                mean_request_seconds=statistics.mean(r['request_seconds'] for r in executed),
                                total_executed_seconds=sum(r['request_seconds'] for r in executed),
                                incomplete=sum(r['termination_reason'] != 'eos' for r in measured),
                                gpu_peak_allocated_gib=max((r.get('gpu_peak_allocated_gib', 0) for r in measured)),
                                process_rss_peak_gib=max((r.get('process_rss_peak_gib', 0) for r in measured))))
    csv_file(out / 'summary.csv', summary)
    return 0 if session['status'] == 'finished' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--match-legacy-pixels', action='store_true')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.run_dir.resolve(), args.match_legacy_pixels)
    else:
        raise SystemExit(run(args.run_dir.resolve()))
