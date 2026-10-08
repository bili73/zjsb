"""Isolated Windows production-concurrency probe; never a serial accuracy benchmark."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import threading
import time

import probe_current_pipeline as base

ROOT = base.ROOT
GLOBAL_SECONDS = 900


class Ids:
    """The raw-to-public identity map lives only in the probe's memory."""
    def __init__(self):
        self.values = {}
        self.counts = Counter()

    def __call__(self, kind, value):
        if value is None:
            return None
        key = (kind, str(value))
        if key not in self.values:
            self.counts[kind] += 1
            self.values[key] = f'{kind}-{self.counts[kind]:04d}'
        return self.values[key]


def prepare(out):
    vault, cases, protocol = base.prepare(out, mode='dual_resident', medical_all=True)
    if len(cases) != 9 or sum(len(c.get('blood_reference', {})) for c in cases) != 72:
        raise base.ProbeError('REFERENCE_SET_CHANGED')
    protocol.update(execution='independent_model_queues',
        scope='Windows production-concurrency probe on overlapping provisional references; not a serial accuracy benchmark, Mac test or HR-hardware qualification.',
        concurrency=dict(document_lanes={'certificate': 1, 'medical': 1}, consumers_per_model=1,
            submit='all nine uploads before polling any task; no wait for a task to finish',
            global_budget_seconds=GLOBAL_SECONDS, global_budget_origin='before first upload, excluding startup',
            active_task_budget_seconds=180, startup='serial load and warmup',
            evidence='paired model-component recognize request_started/request_completed intervals, joined to non-cache attempts; different models and different runs must overlap',
            limitation='Host IPC request overlap, not CUDA-kernel overlap or a claim of higher throughput'),
        timing=dict(upload_to_result_seconds='monotonic upload start to terminal observation; includes polling delay',
            active_elapsed_seconds='persisted runs.ended_at minus tasks.active_started_at',
            task_queue_wait_seconds='persisted tasks.active_started_at minus tasks.created_at',
            model_queue_wait_seconds='prediction.queue_wait_seconds; null when not recorded; never inferred from wall time'))
    protocol['code_hashes'][str(Path(__file__).resolve().relative_to(ROOT))] = base.digest(Path(__file__).read_bytes())
    base.save(out / 'protocol.json', protocol)
    return vault, cases, protocol


def historical_snapshot():
    """Read bytes only; never open/migrate/clean historical business storage."""
    root = ROOT / '.runtime/data'
    return {str(p.relative_to(root)): (p.stat().st_size, base.digest(p.read_bytes()))
            for p in root.rglob('*') if p.is_file()} if root.exists() else {}


def task_row(out, task_id):
    with closing(sqlite3.connect((out / 'private/data/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT t.id,t.run_id,t.status,t.revision,t.created_at,t.active_started_at,
                            t.error_json,r.ended_at FROM tasks t JOIN runs r ON r.id=t.run_id
                            WHERE t.id=?''', (task_id,)).fetchone()
        if row is None:
            raise base.ProbeError('TASK_SNAPSHOT_MISSING')
        return dict(row)


def seconds(start, end):
    if not start or not end:
        return None
    value = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    return value if value >= 0 else None


def capture(out, vault, entry, ids, tasks, fields, attempts, joins, *, http_status=None, interrupted=False):
    from ocr_app.diagnostics import opaque_id
    case = entry['case']
    row = task_row(out, entry['task_id'])
    result, pages, raw = base.published(out, row['id'], row['run_id'], row['revision'])
    (out / 'private' / (case['id'] + '.enc')).write_bytes(vault.pack(dict(result=result, pages=pages, attempts=raw)))
    field_rows, metrics = base.score_case(case, result, pages)
    fields.extend(field_rows)
    errors = json.loads(row['error_json']) if row['error_json'] else {}
    regions = [r for p in pages for r in p.get('regions', []) if r.get('extraction_method') == 'ocr']
    extracted = result.get('fields', []) + result.get('items', [])
    record = dict(case_id=case['id'], doc_type=case['doc_type'], task_id=ids('task', row['id']),
        run_id=ids('run', row['run_id']), result_revision=row['revision'], status=row['status'],
        error_code=errors.get('code'), measured=True, observation_interrupted=interrupted,
        upload_to_result_seconds=None if interrupted else time.monotonic() - entry['start'],
        elapsed_until_interruption_seconds=time.monotonic() - entry['start'] if interrupted else None,
        upload_seconds=entry['upload_seconds'], active_elapsed_seconds=seconds(row['active_started_at'], row['ended_at']),
        task_queue_wait_seconds=seconds(row['created_at'], row['active_started_at']),
        active_elapsed_complete=row['ended_at'] is not None, result_http_status=http_status,
        attempts=len(raw), model_calls=sum(a.get('inference_performed') is True for a in raw),
        cache_hits=sum(a.get('cache_hit') is True for a in raw),
        inference_flag_unknown=sum(a.get('inference_performed') not in (True, False) for a in raw),
        page_count=len(pages), recognized_regions=sum(r.get('status') == 'recognized' for r in regions),
        incomplete_regions=sum(r.get('status') == 'incomplete' for r in regions),
        pending_regions=sum(r.get('status') == 'pending' for r in regions),
        nonrecognized_regions=sum(r.get('status') != 'recognized' for r in regions),
        uncalibrated_confidence_valid=all(f.get('confidence') is None and f.get('confidence_method') == 'unavailable' for f in extracted) if result else None,
        review_contract_valid=base.review_contract_valid(extracted, {f['key'] for f in case.get('fields', []) if f['required']}) if result else None,
        **metrics)
    tasks.append(record)
    for index, attempt in enumerate(raw, 1):
        prediction = attempt.get('prediction') or {}
        region = attempt.get('region_id')
        public = dict(case_id=case['id'], task_id=record['task_id'], run_id=record['run_id'], index=index,
            **{k: attempt.get(k) for k in ('page_index', 'bbox', 'model', 'model_revision', 'task', 'attempt',
                'status', 'error_code', 'input_sha256', 'transform', 'elapsed_seconds', 'timeout_seconds',
                'max_new_tokens', 'generation_timeout_seconds', 'cache_hit', 'inference_performed', 'reused_from_attempt')},
            region_id=ids('region', (row['run_id'], region)),
            reused_from_region_id=ids('region', (row['run_id'], attempt['reused_from_region_id'])) if attempt.get('reused_from_region_id') else None,
            model_queue_wait_seconds=prediction.get('queue_wait_seconds'),
            **{k: prediction.get(k) for k in ('recognition_seconds', 'output_tokens', 'termination_reason',
                'gpu_peak_allocated_gib', 'gpu_peak_reserved_gib')})
        attempts.append(public)
        if attempt.get('inference_performed') is True and not attempt.get('cache_hit'):
            key = (opaque_id(row['id']), opaque_id(row['run_id']), opaque_id(region), attempt.get('model'))
            joins.setdefault(key, []).append(public)
    return record


def diagnostic_evidence(out, ids, joins):
    """Pair actual model IPC boundaries, never queue/runtime completion summaries."""
    records = []
    invalid = 0
    for path in (out / 'diagnostics').glob('ocrdiag-*.jsonl*'):
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
                if event.get('component') == 'model' and event.get('event') in {'request_started', 'request_completed'}:
                    event['_at'] = datetime.fromisoformat(event['timestamp']).timestamp()
                    records.append(event)
            except (ValueError, KeyError, TypeError):
                invalid += 1
    starts, intervals, startup = {}, [], []
    matched_attempts = Counter()
    orphan_completed = 0
    for event in sorted(records, key=lambda e: e['_at']):
        ctx = event.get('context', {})
        op = ctx.get('operation')
        if op not in {'load', 'recognize'}:
            continue
        key = (event.get('process_instance_id'), ctx.get('request_id'), ctx.get('model'), op)
        if event['event'] == 'request_started':
            starts[key] = event
            continue
        start = starts.pop(key, None)
        if start is None:
            orphan_completed += 1
            continue
        begin_ctx = start.get('context', {})
        if any(begin_ctx.get(k) != ctx.get(k) for k in ('task_id', 'run_id', 'region_id')):
            invalid += 1
            continue
        elapsed = event['_at'] - start['_at']
        if elapsed < 0:
            invalid += 1
            continue
        interval = dict(model=ctx.get('model'), operation=op, request_id=ids('request', key),
            started_at=start['timestamp'], completed_at=event['timestamp'], duration_seconds=elapsed)
        if op == 'load':
            startup.append(interval)
            continue
        match_key = (ctx.get('task_id'), ctx.get('run_id'), ctx.get('region_id'), ctx.get('model'))
        candidates = joins.get(match_key, [])
        ordinal = matched_attempts[match_key]
        # Failed calls may have starts without completed events. Match successful predictions only.
        candidates = [a for a in candidates if a.get('recognition_seconds') is not None]
        matched = candidates[ordinal] if ordinal < len(candidates) else None
        matched_attempts[match_key] += 1
        interval.update(task_id=matched['task_id'] if matched else ids('task', ctx.get('task_id')),
            run_id=matched['run_id'] if matched else ids('run', ctx.get('run_id')),
            region_id=matched['region_id'] if matched else ids('diagnostic-region', ctx.get('region_id')),
            case_id=matched['case_id'] if matched else None, attempt_index=matched['index'] if matched else None,
            inference_performed_verified=matched is not None)
        intervals.append(interval)
    overlaps, same_model = [], 0
    def span(a, b):
        start = max(datetime.fromisoformat(a['started_at']), datetime.fromisoformat(b['started_at']))
        end = min(datetime.fromisoformat(a['completed_at']), datetime.fromisoformat(b['completed_at']))
        return max(0., (end - start).total_seconds())
    for i, left in enumerate(intervals):
        for right in intervals[i + 1:]:
            overlap = span(left, right)
            if not overlap:
                continue
            if left['model'] == right['model']:
                same_model += 1
                continue
            verified = left['inference_performed_verified'] and right['inference_performed_verified'] and left['run_id'] != right['run_id']
            overlaps.append(dict(left_request_id=left['request_id'], right_request_id=right['request_id'],
                left_case=left['case_id'], right_case=right['case_id'], left_model=left['model'], right_model=right['model'],
                overlap_seconds=overlap, verified=verified))
    startup_overlap = sum(span(a, b) > 0 for i, a in enumerate(startup) for b in startup[i + 1:])
    verified = sum(row['verified'] for row in overlaps)
    return intervals, startup, overlaps, dict(
        status='passed' if verified > 0 and same_model == 0 and invalid == 0 and len(startup) == 2 and startup_overlap == 0 else 'not_demonstrated',
        verified_cross_model_overlaps=verified, same_model_overlaps=same_model,
        completed_recognition_intervals=len(intervals), matched_inference_intervals=sum(i['inference_performed_verified'] for i in intervals),
        physical_recognition_requests_started=sum(e.get('event') == 'request_started' and e.get('context', {}).get('operation') == 'recognize' for e in records),
        incomplete_started_requests=len(starts), orphan_completed_requests=orphan_completed,
        invalid_records=invalid, startup_load_calls=len(startup), startup_overlaps=startup_overlap,
        startup_serial_verified=len(startup) == 2 and startup_overlap == 0,
        measurement='Host model-request intervals including decode/IPC; not kernel-level GPU overlap')


def export(out, tasks, fields, attempts):
    for name, rows in [('tasks', tasks), ('fields', fields), ('attempts', attempts)]:
        base.csv_file(out / (name + '.csv'), rows)
    base.save(out / 'tasks.json', tasks)


def run(out, port):
    import msvcrt
    import httpx
    import psutil
    from ocr_app.auth import Accounts
    from ocr_app.winjob import JobProcess
    from probe_runtime import OwnedProcesses
    report = dict(status='failed', infrastructure_status='failed', document_status='not_run',
        execution='independent_model_queues', mode='dual_resident',
        scope='Windows production-concurrency probe; not serial accuracy benchmark, Mac test or full clinical accuracy',
        hardware=dict(ram_gib=psutil.virtual_memory().total / 2**30, logical_cpus=psutil.cpu_count(),
            os=platform.system(), python=platform.python_version()))
    tasks, fields, attempts, submitted, joins = [], [], [], [], {}
    owned, ids = OwnedProcesses(), Ids()
    process = lease = observer = protocol = history = None
    cases = []
    stop = threading.Event()
    began = time.monotonic()
    try:
        history = historical_snapshot()
        vault, cases, protocol = prepare(out)
        report['preparation_seconds'] = time.monotonic() - began
        lease = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
        if lease.tell() == 0:
            lease.write(b'1'); lease.flush()
        lease.seek(0)
        try:
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise base.ProbeError('GPU_CHANNEL_BUSY') from None
        hardware = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
        if hardware.returncode == 0:
            report['hardware']['gpu'] = [dict(zip(('model', 'driver', 'memory_mib'), line.split(', '))) for line in hardware.stdout.strip().splitlines()]
        server_start = time.monotonic()
        process = JobProcess([sys.executable, '-u', '-X', 'utf8', str(Path(__file__).resolve()),
            '--serve', '--output', str(out), '--port', str(port)], cwd=ROOT)
        def drain(stream):
            while stream.read(4096):
                pass
        for stream in (process.stdout, process.stderr):
            threading.Thread(target=drain, args=(stream,), daemon=True).start()
        parent = psutil.Process(process.pid)
        owned.remember(parent, 'api')
        def observe():
            while not stop.wait(.1):
                try:
                    for child in parent.children(recursive=True):
                        try:
                            owned.remember(child)
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    return
                except (psutil.Error, OSError):
                    report['observer_error'] = 'PROCESS_OBSERVATION_FAILED'
        observer = threading.Thread(target=observe, daemon=True)
        observer.start()
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
            startup_deadline = time.monotonic() + 260
            while True:
                if process.poll() is not None:
                    raise base.ProbeError('API_PROCESS_EXITED')
                try:
                    health = client.get('/health').json()
                    report.setdefault('http_ready_seconds', time.monotonic() - server_start)
                    snapshot = health.get('runtime', {})
                    if snapshot.get('state') in {'ready', 'degraded'}:
                        if snapshot.get('effective_mode') != 'dual_resident' or sum(v == 'ready' for v in snapshot.get('models', {}).values()) != 2:
                            raise base.ProbeError('RUNTIME_NOT_READY')
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= startup_deadline:
                    raise base.ProbeError('STARTUP_TIMEOUT')
                time.sleep(.2)
            report['startup_seconds'] = time.monotonic() - server_start
            client.headers['X-API-Key'] = Accounts(base.read_only_storage(out / 'private/data')).current_key()
            if client.get('/api/v1/auth/me').status_code != 200:
                raise base.ProbeError('AUTH_FAILED')
            workload_start = time.monotonic()
            deadline = workload_start + GLOBAL_SECONDS
            for case in cases:
                data = vault.read(case['input_ref'])
                if base.digest(data) != case['input_sha256']:
                    raise base.ProbeError('INPUT_CHANGED')
                if time.monotonic() >= deadline:
                    raise base.ProbeError('GLOBAL_POLL_TIMEOUT')
                start = time.monotonic()
                response = client.post('/api/v1/batches', data={'doc_type_hint': case['doc_type']},
                    files=[('files', (case['id'] + case['suffix'], data, 'application/octet-stream'))],
                    timeout=min(30., max(.001, deadline - start)))
                if response.status_code != 202:
                    raise base.ProbeError('UPLOAD_FAILED')
                submitted.append(dict(case=case, task_id=response.json()['task_ids'][0], start=start,
                    upload_seconds=time.monotonic() - start))
            report['all_uploads_seconds'] = time.monotonic() - workload_start
            pending = list(submitted)
            while pending:
                if process.poll() is not None:
                    raise base.ProbeError('API_PROCESS_EXITED')
                for entry in list(pending):
                    if time.monotonic() >= deadline:
                        raise base.ProbeError('GLOBAL_POLL_TIMEOUT')
                    response = client.get('/api/v1/tasks/' + entry['task_id'], timeout=min(10., max(.001, deadline - time.monotonic())))
                    if response.status_code != 200:
                        raise base.ProbeError('TASK_READ_FAILED')
                    if response.json()['status'] not in base.TERMINAL:
                        continue
                    response = client.get('/api/v1/tasks/' + entry['task_id'] + '/result', timeout=min(10., max(.001, deadline - time.monotonic())))
                    record = capture(out, vault, entry, ids, tasks, fields, attempts, joins, http_status=response.status_code)
                    pending.remove(entry)
                    export(out, tasks, fields, attempts)
                    print(json.dumps(dict(case_id=record['case_id'], status=record['status'],
                        active_seconds=record['active_elapsed_seconds'])), flush=True)
                if pending:
                    time.sleep(min(.25, max(0., deadline - time.monotonic())))
            report['workload_seconds'] = time.monotonic() - workload_start
            report['infrastructure_status'] = 'passed'
            report['document_status'] = 'passed' if all(t['status'] in {'NEED_REVIEW', 'COMPLETED'} for t in tasks) else 'partial'
            report['status'] = report['document_status']
    except Exception as error:
        report['failure_code'] = str(error) if isinstance(error, base.ProbeError) else 'PROBE_FAILED'
    finally:
        if process:
            close_start = time.monotonic()
            try:
                if process.poll() is None:
                    try:
                        process.stdin.write('stop\n'); process.stdin.flush(); process.wait(timeout=15)
                    except (OSError, TimeoutError):
                        pass
            except Exception:
                report['shutdown_error'] = 'GRACEFUL_SHUTDOWN_FAILED'
            finally:
                try:
                    process.close()
                except Exception:
                    report['close_error'] = 'PROCESS_CLEANUP_FAILED'
            report['cleanup_seconds'] = time.monotonic() - close_start
        stop.set()
        if observer:
            observer.join(timeout=2)
        try:
            processes, report['cleanup_wait_seconds'] = owned.wait_all(timeout=5)
            report['owned_processes'] = [dict(process_id=ids('process', (p['pid'], p['create_time'])),
                role=p['role'], signaled=p['signaled'], wait_result=p['wait_result']) for p in processes]
            if any(not p['signaled'] for p in processes) or report.get('close_error') or report.get('observer_error'):
                report.update(status='failed', infrastructure_status='failed')
        except Exception:
            report.update(status='failed', infrastructure_status='failed', close_error='EXIT_OBSERVATION_FAILED')
        finally:
            try:
                owned.close()
            except Exception:
                report.update(status='failed', infrastructure_status='failed', close_error='HANDLE_CLEANUP_FAILED')
            if lease:
                lease.close()
        for entry in submitted:
            if any(t['case_id'] == entry['case']['id'] for t in tasks):
                continue
            try:
                capture(out, vault, entry, ids, tasks, fields, attempts, joins, interrupted=True)
            except Exception:
                field_rows, metrics = base.score_case(entry['case'], {}, [])
                fields.extend(field_rows)
                tasks.append(dict(case_id=entry['case']['id'], doc_type=entry['case']['doc_type'],
                    measured=True, status='PROBE_INTERRUPTED', snapshot_error='SNAPSHOT_UNAVAILABLE', **metrics))
        report['planned_cases'], report['submitted_cases'] = len(cases), len(submitted)
        for case in cases:
            if any(t['case_id'] == case['id'] for t in tasks):
                continue
            unrun, metrics = base.score_case(case, None, [])
            fields.extend({**row, 'outcome': 'not_run'} for row in unrun)
            tasks.append(dict(case_id=case['id'], doc_type=case['doc_type'], status='NOT_RUN', measured=False,
                **{**metrics, 'field_accuracy': None, 'missing': 0, 'required_reference_missing': None, 'runtime_required_missing': None}))
        try:
            intervals, startup, overlap, evidence = diagnostic_evidence(out, ids, joins)
            report['concurrency'] = evidence
            report['model_calls'] = sum(a.get('inference_performed') is True for a in attempts)
            report['cache_hits'] = sum(a.get('cache_hit') is True for a in attempts)
            report['model_calls_measurement'] = 'Attempt inference_performed flags; queue rejection can precede actual dispatch. See matched_inference_intervals for completed physical requests.'
            if report['model_calls'] == 0:
                report['concurrency']['status'] = 'not_demonstrated'
            for name, rows in [('recognition_intervals', intervals), ('startup_intervals', startup), ('overlap', overlap)]:
                base.csv_file(out / (name + '.csv'), rows)
                base.save(out / (name + '.json'), rows)
            if evidence['status'] != 'passed' and report['status'] == 'passed':
                report['status'] = 'partial'
            controls = {t['case_id']: t for t in tasks}
            report['synthetic_controls'] = dict(
                native_bypassed_ocr=controls.get('synthetic-pdf', {}).get('attempts') == 0,
                image_exercised_glm=any(a['case_id'] == 'synthetic-image' and a.get('model') == 'glm_ocr'
                    and a.get('inference_performed') is True for a in attempts))
            if not all(report['synthetic_controls'].values()) and report['status'] == 'passed':
                report['status'] = 'partial'
        except Exception:
            report.update(status='failed', infrastructure_status='failed', diagnostic_error='EVIDENCE_FAILED')
        if protocol:
            report['provenance_unchanged'] = all((ROOT / p).is_file() and base.digest((ROOT / p).read_bytes()) == sha
                for group in ('code_hashes', 'source_hashes') for p, sha in protocol[group].items())
            if not report['provenance_unchanged']:
                report.update(status='failed', infrastructure_status='failed', failure_code='PROVENANCE_CHANGED')
        if history is not None:
            try:
                report['historical_store'] = dict(files=len(history), bytes=sum(v[0] for v in history.values()),
                    unchanged=history == historical_snapshot())
                if not report['historical_store']['unchanged']:
                    report.update(status='failed', infrastructure_status='failed', failure_code='HISTORICAL_STORE_CHANGED')
            except Exception:
                report.update(status='failed', infrastructure_status='failed', failure_code='HISTORICAL_STORE_CHECK_FAILED')
        export(out, tasks, fields, attempts)
        report['elapsed_seconds'] = time.monotonic() - began
        base.save(out / 'summary.json', report)
    return 0 if report['status'] in {'passed', 'partial'} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/concurrent-pipeline-20261008-v1')
    parser.add_argument('--port', type=int, default=8784)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise base.ProbeError('INVALID_PORT')
        if args.serve:
            base.serve(args.output, args.port)
            return 0
        out = base.isolated_output(args.output)
        if args.prepare_only:
            _, cases, protocol = prepare(out)
            print(json.dumps(dict(status='prepared', cases=len(cases), execution=protocol['execution'])), flush=True)
            return 0
        return run(out, args.port)
    except Exception as error:
        print(json.dumps(dict(status='failed', code=str(error) if isinstance(error, base.ProbeError) else 'PROBE_FAILED')), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
