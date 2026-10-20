"""Isolated Windows concurrency acceptance; never a serial accuracy benchmark.

Requires the idle live GPU owner stopped. Existing storage is read-only;
synthetic accounts, results and keys stay under a new encrypted output directory.
"""
import argparse
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from probe_current_pipeline import read_only_storage
from probe_photo_tables import require_idle
from probe_runtime_batches import Http, cohort, save
from ocr_app.extraction import extract_fields
from ocr_app.storage import Storage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixtures(source):
    storage = read_only_storage(ROOT / '.runtime/data')
    data = source.read_bytes()
    target = dict(id='target', kind='DIPLOMA', data=data, name='target.jpg', owner=0)
    peers, medical, seen = [], None, {digest(data)}
    with sqlite3.connect((ROOT / '.runtime/data/tasks.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        for row in db.execute("SELECT * FROM tasks WHERE doc_type IN ('DIPLOMA','MEDICAL_REPORT') ORDER BY created_at DESC"):
            meta = storage.unpack(row['meta_enc'])
            if row['content_hash'] in seen or row['status'] not in {'NEED_REVIEW', 'COMPLETED'}:
                continue
            if row['doc_type'] == 'DIPLOMA' and len(peers) < 2 and meta.get('actual_source_page_count') == 1:
                value = storage.read(row['input_ref'])
                if value.startswith(b'%PDF'):
                    continue
                seen.add(row['content_hash'])
                peers.append(dict(id='peer-'+str(len(peers)+1), kind='DIPLOMA', data=value,
                                  name='peer-'+str(len(peers)+1)+'.jpg', owner=len(peers)+1))
            if row['doc_type'] == 'MEDICAL_REPORT' and medical is None and (meta.get('actual_source_page_count') or 0) >= 20:
                pages = storage.unpack(row['pages_enc'], [])
                regions = [region for page in pages for region in page.get('regions', []) if region.get('extraction_method') == 'ocr']
                if not regions or any(region['status'] != 'recognized' for region in regions):
                    continue
                value = storage.read(row['input_ref'])
                if value.startswith(b'%PDF'):
                    medical = dict(id='medical', kind='MEDICAL_REPORT', data=value, name='medical.pdf', owner=0)
            if len(peers) == 2 and medical is not None:
                break
    assert len(peers) == 2 and medical is not None, 'NEED_TWO_CERTIFICATES_AND_A_COMPLETE_LONG_REPORT'
    return target, peers, medical


def recovery_detail(business, filename, out):
    task = next(task for task in business.store.tasks() if task.get('file_name') == filename)
    result = business.store.result(task['task_id'])
    with sqlite3.connect(business.engine.url.database) as db:
        values = db.execute('SELECT payload_enc FROM attempts WHERE task_id=? AND run_id=? ORDER BY created_at,id',
                            (task['task_id'], task['run_id'])).fetchall()
    attempts = [business.storage.unpack(value[0]) for value in values]
    primary = [dict(text=a['prediction']['text'], page=a['page_index'], region_id=a['region_id'],
                    bbox=a['bbox'], extraction_method='ocr') for a in attempts
               if not a.get('recovery_fields') and (a.get('prediction') or {}).get('text')]
    before = {f['key']: f.get('value') for f in extract_fields(primary, 'DIPLOMA')}
    after = {f['key']: f.get('value') for f in result['fields']}
    retries = [a for a in attempts if a.get('recovery_fields')]
    changed = [key for key, value in before.items() if value is not None and after.get(key) != value]
    (out / 'private' / (filename+'.enc')).write_bytes(business.storage.pack(dict(result=result, attempts=attempts)))
    detail = dict(id=filename, status=task['status'], primary_major_missing=before.get('major') is None,
                  major_filled=bool(after.get('major')), changed_primary_fields=changed,
                  recovery_attempts=len(retries), retries=[dict(input_sha256=a['input_sha256'],
                      batch_policy=a.get('batch_policy'), batch_size=(a.get('prediction') or {}).get('batch_size'),
                      termination=(a.get('prediction') or {}).get('termination_reason'),
                      queue_wait_seconds=(a.get('prediction') or {}).get('queue_wait_seconds')) for a in retries])
    assert task['status'] == 'NEED_REVIEW' and not changed and detail['major_filled'], 'RECOVERY_RESULT_NOT_PRESERVED'
    assert len(retries) <= 1 and (retries or not detail['primary_major_missing']), 'RECOVERY_NOT_EXERCISED'
    assert all(a['batch_policy'] == 'single' and a['batch_size'] == 1 and a['termination'] == 'eos'
               for a in detail['retries']), 'RECOVERY_BATCH_POLICY_NOT_ENFORCED'
    return detail


def run(out, source):
    import uvicorn
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.diagnostics import init_diagnostics

    target, peers, medical = fixtures(source)
    diagnostic = init_diagnostics(out/'diagnostics', 'api')
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(diagnostic.root)
    os.environ['OCR_DIAGNOSTICS_SESSION'] = diagnostic.session_id
    business = Business(out/'private/data', diagnostic)
    business.prepare()
    (out/'private/sources.enc').write_bytes(business.storage.pack(dict(source=str(source.resolve()),
        inputs=[dict(id=case['id'], sha256=digest(case['data'])) for case in [target, *peers, medical]])))
    password = secrets.token_urlsafe(24)
    accounts = [business.accounts.set_user('recovery-test-'+str(i), password, '测试账号'+str(i),
                                          'admin' if i == 0 else 'operator') for i in range(3)]
    runtime = RuntimeClient(RuntimeConfig(out/'session', data_root=business.root, model_batch_size=2))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    app = create_app(runtime, ROOT/'frontend/dist', out/'session', business, diagnostic)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
    thread = threading.Thread(target=server.run, kwargs=dict(sockets=[sock]), daemon=True)
    clients, metrics = [], []
    report = dict(execution='isolated_dual_resident_concurrency', serial_accuracy_benchmark=False,
                  source_sha256=digest(target['data']), rounds=[], recoveries=[], code_hashes={}, mac_operations=0)
    for name in ['backend/ocr_app/pipeline.py', 'backend/ocr_app/model_queues.py',
                 'backend/runtime_worker.py', 'backend/ocr_app/task_scheduler.py', str(Path(__file__).relative_to(ROOT))]:
        report['code_hashes'][name] = digest((ROOT/name).read_bytes().replace(b'\r\n', b'\n'))
    began = time.monotonic()
    thread.start()
    try:
        until = time.monotonic()+20
        while not server.started and time.monotonic() < until:
            time.sleep(.1)
        assert server.started, 'SERVER_NOT_STARTED'
        clients = [Http('http://127.0.0.1:'+str(port), 'ABC'[i], metrics) for i in range(3)]
        for i, client in enumerate(clients):
            client.login(accounts[i]['username'], password)
        password = None
        until = time.monotonic()+360
        while time.monotonic() < until:
            if clients[0].call('health', '/api/v1/health')['runtime']['state'] == 'ready':
                break
            time.sleep(1)
        else:
            raise RuntimeError('DUAL_MODELS_NOT_READY')
        report['startup_seconds'] = round(time.monotonic()-began, 3)
        routes = [('health', '/health'), ('batches', '/api/v1/batches?page=1&page_size=50'), ('static', '/')]
        for index in range(1, 4):
            cases = [{**case, 'id':case['id']+'-'+str(index), 'name':case['id']+'-'+str(index)+'.jpg'}
                     for case in [target, *peers]]
            if index == 1:
                cases.append(medical)
            print(json.dumps(dict(event='round_start', index=index, files=len(cases))), flush=True)
            report['rounds'].append(cohort(business, runtime, clients, cases, 'round-'+str(index), metrics, routes, out))
            report['recoveries'].append(recovery_detail(business, 'target-'+str(index)+'.jpg', out))
            save(out/'report.json', report)
        report['statistics'] = runtime.request('statistics', wait=10)
        calls = [m for m in report['statistics']['metrics'] if m.get('operation') == 'recognize_batch']
        report['ordinary_two_row_calls'] = sum(m.get('batch_size') == 2 for m in calls)
        report['cross_model_overlaps'] = sum(g['model'] != p['model'] and
            max(g['started_monotonic'], p['started_monotonic']) < min(g['finished_monotonic'], p['finished_monotonic'])
            for i, g in enumerate(calls) for p in calls[i+1:])
        assert report['ordinary_two_row_calls'] > 0, 'ORDINARY_BATCHING_NOT_EXERCISED'
        assert report['cross_model_overlaps'] > 0, 'CROSS_MODEL_OVERLAP_NOT_OBSERVED'
        assert all(case['status'] == 'NEED_REVIEW' and not (case.get('progress') or {}).get('incomplete_regions')
                   for cohort_result in report['rounds'] for case in cohort_result['cases']), 'INCOMPLETE_CASE'
        assert all(not round_result['sampling_errors'] for round_result in report['rounds']), 'LOADING_FAILED'
        report['passed'] = True
    finally:
        server.should_exit = True
        thread.join(30)
        if thread.is_alive():
            runtime.close(graceful=False); thread.join(5)
        report['runtime_stopped'] = runtime.is_stopped()
        report['source_unchanged'] = digest(source.read_bytes()) == report['source_sha256']
        report['http_metrics'] = metrics
        diagnostic.close()
        save(out/'report.json', report)
        assert not thread.is_alive() and report['runtime_stopped'], 'PROBE_NOT_STOPPED'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to(ROOT/'output') and out != ROOT/'output', 'OUTPUT_NOT_ISOLATED'
    require_idle()
    out.mkdir(exist_ok=False)
    with (ROOT/'output/two-model-retest-gpu.lock').open('a+b') as lease:
        lease.seek(0); msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        require_idle()
        run(out, args.source)
    print(json.dumps(dict(passed=True, output=str(out))), flush=True)


if __name__ == '__main__':
    main()
