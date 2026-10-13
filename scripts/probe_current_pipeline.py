"""Isolated real HTTP acceptance. No model runs on import or --prepare-only."""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage, _dpapi, AESGCM
from schema_extraction import score

CERT = ROOT / 'output/dual-extraction-20260930-v1'
MEDICAL = ROOT / 'output/medical-corpus-20260930-v2'
TITLE = ROOT / 'output/field-mapping-replay-20260930-v1/native/title_lookup.json'
TERMINAL = {'NEED_REVIEW', 'COMPLETED', 'FAILED', 'CANCELLED', 'REJECTED'}
TIMEOUTS = {'EXTRACT_TIMEOUT', 'MODEL_REQUEST_TIMEOUT', 'TASK_POLL_TIMEOUT', 'SUPERVISION_FAILED', 'WORKER_INTERRUPTED'}


class ProbeError(RuntimeError):
    """Only fixed codes, never external exception messages."""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def csv_file(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)


def isolated_output(path, *, new=True, base=None):
    base = (base or ROOT / 'output').resolve()
    out = Path(path).resolve()
    if out == base or not out.is_relative_to(base):
        raise ProbeError('OUTPUT_NOT_ISOLATED')
    if new:
        out.mkdir(parents=True, exist_ok=False)
    elif not (out / 'protocol.json').is_file():
        raise ProbeError('PREPARED_OUTPUT_REQUIRED')
    for child in ('private/data', 'private/fixtures', 'session', 'diagnostics'):
        if not (out / child).resolve().is_relative_to(out):
            raise ProbeError('OUTPUT_NOT_ISOLATED')
    return out


def read_only_storage(root):
    """Do not invoke Storage.__init__ against a historical directory."""
    root = Path(root).resolve()
    key_file = root.parent / 'secrets/data-key.dpapi'
    if not root.is_dir() or not key_file.is_file():
        raise ProbeError('FROZEN_STORAGE_UNAVAILABLE')
    value = Storage.__new__(Storage)
    value.root, value.blobs = root, root / 'blobs'
    value.cipher = AESGCM(_dpapi(key_file.read_bytes(), decrypt=True))
    return value


def frozen(folder):
    protocol = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))
    data = (folder / 'private/fixture.enc').read_bytes()
    if digest(data) != protocol['fixture_sha256']:
        raise ProbeError('FROZEN_FIXTURE_HASH_MISMATCH')
    storage = read_only_storage(folder / 'private/data')
    return protocol, storage, storage.unpack(data)


def synthetic():
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    values = dict(name='测试样本', gender='男', school_name='示例大学', major='计算机科学',
                  education_level='本科', graduate_date='2026-06-30', certificate_no='123456202605000001')
    lines = ['毕业证书', '姓名：测试样本', '性别：男', '学校名称：示例大学', '专业：计算机科学',
             '学历层次：本科', '毕业日期：2026年6月30日', '证书编号：123456202605000001']
    with fitz.open() as document:
        page = document.new_page(width=700, height=900)
        for index, line in enumerate(lines):
            page.insert_text((50, 80 + index * 65), line, fontname='china-s', fontsize=22)
        pdf = document.tobytes()
    image = Image.new('RGB', (1000, 1200), 'white')
    draw, font = ImageDraw.Draw(image), ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 40)
    for index, line in enumerate(lines):
        draw.text((70, 80 + index * 100), line, font=font, fill='black')
    buffer = io.BytesIO(); image.save(buffer, format='PNG'); image.close()
    return [('synthetic-pdf', '.pdf', pdf), ('synthetic-image', '.png', buffer.getvalue())], values


def prepare(out, *, mode='single_resident', medical_all=False):
    cert_protocol, cert_storage, fixture = frozen(CERT)
    med_protocol, med_storage, medical = frozen(MEDICAL)
    vault = Storage(out / 'private/fixtures')
    cases = []
    def add(alias, kind, suffix, data, **reference):
        cases.append(dict(id=alias, doc_type=kind, suffix=suffix, input_ref=vault.put(data),
                          input_sha256=digest(data), **reference))
    samples, values = synthetic()
    fields = fixture['templates']['DIPLOMA']
    reference = {f['key']: dict(status='present' if f['key'] in values else 'absent', value=values.get(f['key'])) for f in fields}
    for alias, suffix, data in samples:
        add(alias, 'DIPLOMA', suffix, data, reference=reference, fields=fields)
    selected = [s for s in fixture['samples'] if s['doc_type'] in {'DIPLOMA', 'DEGREE_CERT'}]
    if len(selected) != 4:
        raise ProbeError('CERTIFICATE_SET_CHANGED')
    manifest = {s['id']: s for s in cert_protocol['sample_manifest']}
    for sample in selected:
        data = cert_storage.read(sample['image_ref'])
        if digest(data) != sample['input_sha256'] or manifest[sample['id']]['input_sha256'] != sample['input_sha256']:
            raise ProbeError('FROZEN_INPUT_HASH_MISMATCH')
        add(sample['id'], sample['doc_type'], '.png', data, reference=sample['reference'],
            fields=fixture['templates'][sample['doc_type']], source_sha256=sample['source_sha256'])
    counts = Counter(r['status'] for s in selected for r in s['reference'].values())
    if dict(counts) != dict(present=39, absent=4, uncertain=6):
        raise ProbeError('CERTIFICATE_REFERENCE_CHANGED')
    sources_path = MEDICAL / 'private/sources.enc'
    medical_ids = ('report-002', 'report-003', 'report-004') if medical_all else ('report-004',)
    sources = med_storage.unpack(sources_path.read_bytes())
    for medical_id in medical_ids:
        source = next(s for s in sources if s['id'] == medical_id)
        data = med_storage.read(source['source_ref'])
        original = next(s for s in med_protocol['documents'] if s['id'] == source['id'])
        if digest(data) != source['source_sha256'] or source['source_sha256'] != original['source_sha256'] or len(data) != original['bytes']:
            raise ProbeError('FROZEN_INPUT_HASH_MISMATCH')
        blood = [s for s in medical if s['document_id'] == source['id'] and s.get('visual_reference')]
        if not blood or any((s['page'], s['visual_reference']) != (blood[0]['page'], blood[0]['visual_reference']) for s in blood) or len(blood[0]['visual_reference']) != 24:
            raise ProbeError('MEDICAL_REFERENCE_CHANGED')
        title = next(s for s in json.loads(TITLE.read_text(encoding='utf-8'))['title_matches'] if s['document_id'] == source['id'])
        add(source['id'], 'MEDICAL_REPORT', '.pdf', data, blood_page=blood[0]['page'], blood_reference=blood[0]['visual_reference'],
            summary_reference=dict(scope='follow_up_required', declared_count=int(title['declared_count']), page=title['page']))
    encrypted = vault.pack(cases); (out / 'private/cases.enc').write_bytes(encrypted)
    code = sorted([*ROOT.glob('backend/**/*.py'), ROOT / 'scripts/schema_extraction.py', Path(__file__).resolve(), ROOT / 'SPEC.md', ROOT / 'openapi.yaml'])
    protocol = dict(probe='current_pipeline_acceptance', schema_version=2, mode=mode, prepared_at=time.time(), cases_sha256=digest(encrypted),
        cases=[{k: s[k] for k in ('id', 'doc_type', 'input_sha256')} for s in cases],
        source_hashes={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in [CERT / 'protocol.json', CERT / 'private/fixture.enc', MEDICAL / 'protocol.json', MEDICAL / 'private/fixture.enc', sources_path, TITLE]},
        code_hashes={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in code},
        checkpoints={name: json.loads((ROOT / 'models' / name / 'download_manifest.json').read_text())['revision'] for name in ('glm-ocr', 'paddleocr-vl')},
        certificate_references=dict(counts), max_new_tokens=4096, task_budget_seconds=180, medical_generation_timeout_seconds=20,
        scoring='Frozen schema scorer; absent and uncertain separate; failed cases keep denominators. Medical basic info unscored; blood24 raw whitespace comparison and scoped summary checked separately.',
        scope='Real API acceptance with explicit residency; provisional overlapping references, not held-out accuracy, throughput, Mac or HR-hardware qualification.')
    save(out / 'protocol.json', protocol)
    return vault, cases, protocol


def norm(value):
    return re.sub(r'\s+', '', str(value))


def review_contract_valid(extracted, required):
    for field in extracted:
        issues, review = field.get('review_issues'), field.get('need_review')
        if not isinstance(issues, list) or not isinstance(review, bool) or review != bool(issues):
            return False
        if field.get('key') in required and field.get('value') in (None, '') and not review:
            return False
    return True


def score_case(case, result, pages):
    """Only anonymous outcomes leave this function; result is private published data."""
    result = result or {}
    rows, conflicts = [], set()
    values = {}
    if case['doc_type'] != 'MEDICAL_REPORT':
        grouped = {}
        for field in result.get('fields', []):
            key = field.get('key')
            grouped.setdefault(key, []).append(field.get('value'))
            if field.get('review_reason') == 'CONFLICT' or any(i.get('code') == 'CONFLICT' for i in field.get('review_issues', [])):
                conflicts.add(key)
        for key, candidates in grouped.items():
            if len(candidates) > 1:
                conflicts.add(key)
        values = {key: candidates[0] if key not in conflicts else None for key, candidates in grouped.items()}
        rows = [{**row, 'conflict': row['field'] in conflicts} for row in score(case['reference'], values, case['fields'])]
    else:
        for key, expected in case['blood_reference'].items():
            found = [norm(item['result_raw']) for item in result.get('items', [])
                     if item.get('source', {}).get('page') == case['blood_page']
                     and norm(key) in {norm(item.get('alias', '')), norm(item.get('name', ''))}]
            conflict = len(found) > 1
            outcome = 'missing' if not found or conflict else 'correct' if found[0] == norm(expected) else 'wrong'
            rows.append(dict(field=key, required=True, reference_status='present', outcome=outcome, conflict=conflict,
                             duplicate_match_count=len(found) if conflict else 0))
    counts = Counter(row['outcome'] for row in rows)
    denominator = sum(row['reference_status'] == 'present' for row in rows)
    summary = dict(field_correct=counts['correct'], field_total=denominator,
        field_accuracy=counts['correct'] / denominator if denominator else None,
        missing=counts['missing'], wrong=counts['wrong'], conflict=sum(r['conflict'] for r in rows),
        required_reference_missing=sum(r['required'] and r['outcome'] == 'missing' for r in rows),
        runtime_required_missing=sum(f['required'] and values.get(f['key']) in (None, '') for f in case.get('fields', [])) if case.get('fields') else None,
        required_present_total=sum(r['required'] and r['reference_status'] == 'present' for r in rows),
        required_uncertain_total=sum(r['required'] and r['reference_status'] == 'uncertain' for r in rows),
        absent_total=sum(r['reference_status'] == 'absent' for r in rows), correct_absence=counts['correct_absence'],
        false_positive=counts['false_positive'], unscored=counts['unscored'],
        medical_basic_accuracy=None, score_scope='blood24' if case['doc_type'] == 'MEDICAL_REPORT' else 'certificate_fields')
    if case['doc_type'] == 'MEDICAL_REPORT':
        report = result.get('report_summary', {})
        findings = report.get('findings', [])
        sources = report.get('sources', []) + [s for f in findings for s in f.get('sources', [])]
        known = {(p['page_index'], r.get('region_id')) for p in pages for r in p.get('regions', [])}
        expected = case['summary_reference']
        summary.update(summary_scope=report.get('scope'), summary_declared=report.get('declared_count'),
            summary_findings=len(findings) if report else None, summary_count_check=report.get('count_check'),
            summary_pages=sorted({s['page'] for s in sources if 'page' in s}), summary_sources_total=len(sources),
            summary_sources_resolved=sum((s.get('page'), s.get('region_id')) in known for s in sources),
            summary_declared_correct=report.get('scope') == expected['scope'] and report.get('declared_count') == expected['declared_count'],
            summary_observed_count_correct=report.get('scope') == expected['scope'] and len(findings) == expected['declared_count'],
            summary_expected_page_present=any(s.get('page') == expected['page'] for s in sources))
    return [dict(case_id=case['id'], **row) for row in rows], summary


def published(out, task_id, run_id, revision):
    storage = read_only_storage(out / 'private/data')
    with closing(sqlite3.connect((out / 'private/data/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as database:
        database.execute('BEGIN')
        row = database.execute('SELECT run_id,result_enc,pages_enc,revision FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row or row[0] != run_id or row[3] != revision:
            raise ProbeError('RESULT_VERSION_MISMATCH')
        attempts = [storage.unpack(r[0]) for r in database.execute('SELECT payload_enc FROM attempts WHERE run_id=? ORDER BY created_at,rowid', (run_id,))]
    return storage.unpack(row[1], {}), storage.unpack(row[2], []), attempts


def serve(out, port):
    # No launcher, saved mode, default data root, or historical retention is used.
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.diagnostics import init_diagnostics
    import uvicorn
    out = isolated_output(out, new=False)
    protocol = json.loads((out / 'protocol.json').read_text(encoding='utf-8'))
    if protocol.get('probe') != 'current_pipeline_acceptance' or (out / 'private/data/tasks.sqlite3').exists():
        raise ProbeError('FRESH_ISOLATED_DATA_REQUIRED')
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(out / 'diagnostics')
    logger = init_diagnostics(out / 'diagnostics', 'api')
    business = Business(out / 'private/data', logger=logger)
    business.prepare()
    mode = json.loads((out / 'protocol.json').read_text(encoding='utf-8'))['mode']
    if mode not in {'single_resident', 'dual_resident'}:
        raise ProbeError('INVALID_MODE')
    runtime = RuntimeClient(RuntimeConfig(out / 'session', mode=mode, data_root=business.root))
    app = create_app(runtime, ROOT / 'frontend/dist', out / 'session', business=business, logger=logger)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, access_log=False, log_level='critical'))
    def stop_on_parent():
        sys.stdin.readline()
        server.should_exit = True
    threading.Thread(target=stop_on_parent, daemon=True).start()
    try:
        server.run()
    finally:
        failed = False
        for close in (lambda: runtime.close(graceful=False), business.close, logger.close):
            try:
                close()
            except Exception:
                failed = True
        if failed:
            raise ProbeError('SERVER_CLEANUP_FAILED') from None


def run(out, port, *, mode='single_resident', medical_all=False):
    import msvcrt
    import httpx
    import psutil
    from ocr_app.winjob import JobProcess
    from probe_runtime import OwnedProcesses
    from ocr_app.auth import Accounts
    report = dict(status='failed', infrastructure_status='failed', document_status='not_run', mode=mode,
                  hardware=dict(ram_gib=psutil.virtual_memory().total / 2**30, logical_cpus=psutil.cpu_count(), os=platform.system(), python=platform.python_version()))
    tasks, fields, attempts, owned = [], [], [], OwnedProcesses()
    cases, protocol, active = [], None, None
    process = lease = observer = None
    stop = threading.Event(); began = time.monotonic()
    try:
        vault, cases, protocol = prepare(out, mode=mode, medical_all=medical_all)
        report['preparation_seconds'] = time.monotonic() - began
        lease = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
        if lease.tell() == 0:
            lease.write(b'1'); lease.flush()
        lease.seek(0)
        try:
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ProbeError('GPU_CHANNEL_BUSY') from None
        hardware = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
        if hardware.returncode == 0:
            report['hardware']['gpu'] = [dict(zip(('model', 'driver', 'memory_mib'), line.split(', '))) for line in hardware.stdout.strip().splitlines()]
        server_start = time.monotonic()
        process = JobProcess([sys.executable, '-u', '-X', 'utf8', str(Path(__file__).resolve()), '--serve', '--output', str(out), '--port', str(port)], cwd=ROOT)
        def drain(stream):
            while stream.read(4096):
                pass
        for stream in (process.stdout, process.stderr):
            threading.Thread(target=drain, args=(stream,), daemon=True).start()
        parent = psutil.Process(process.pid); owned.remember(parent, 'api')
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
        observer = threading.Thread(target=observe, daemon=True); observer.start()
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
            deadline = time.monotonic() + 260
            while True:
                if process.poll() is not None:
                    raise ProbeError('API_PROCESS_EXITED')
                try:
                    client.get('/health').raise_for_status()
                    if 'X-API-Key' not in client.headers:
                        client.headers['X-API-Key'] = Accounts(read_only_storage(out / 'private/data')).current_key()
                    response = client.get('/api/v1/health')
                    if response.status_code == 401:
                        raise ProbeError('AUTH_FAILED')
                    response.raise_for_status()
                    health = response.json()
                    if 'http_ready_seconds' not in report:
                        report['http_ready_seconds'] = time.monotonic() - server_start
                    snapshot = health.get('runtime', {})
                    if snapshot.get('state') in {'ready', 'degraded'}:
                        if snapshot.get('effective_mode') != mode or sum(v == 'ready' for v in snapshot.get('models', {}).values()) != (2 if mode == 'dual_resident' else 1):
                            raise ProbeError('RUNTIME_NOT_READY')
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise ProbeError('STARTUP_TIMEOUT')
                time.sleep(.2)
            report['startup_seconds'] = time.monotonic() - server_start
            if client.get('/api/v1/auth/me').status_code != 200:
                raise ProbeError('AUTH_FAILED')
            for case in cases:
                data = vault.read(case['input_ref'])
                if digest(data) != case['input_sha256']:
                    raise ProbeError('INPUT_CHANGED')
                start = time.monotonic()
                response = client.post('/api/v1/batches', data={'doc_type_hint': case['doc_type']}, files=[('files', (case['id'] + case['suffix'], data, 'application/octet-stream'))])
                if response.status_code != 202:
                    raise ProbeError('UPLOAD_FAILED')
                task_id = response.json()['task_ids'][0]
                active = dict(case=case, task_id=task_id, start=start)
                deadline = time.monotonic() + 215
                timed_out = False
                while True:
                    response = client.get('/api/v1/tasks/' + task_id)
                    if response.status_code != 200:
                        raise ProbeError('TASK_READ_FAILED')
                    task = response.json()
                    if task['status'] in TERMINAL:
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    time.sleep(.25)
                response = client.get('/api/v1/tasks/' + task_id + '/result')
                wall = time.monotonic() - start
                result, pages, raw_attempts = published(out, task_id, task['run_id'], task['result_revision'])
                field_rows, metrics = score_case(case, result, pages)
                fields.extend(field_rows)
                error_code = 'TASK_POLL_TIMEOUT' if timed_out else (task.get('error') or {}).get('code')
                # Published task rows, not masked HTTP values or unpublished run history, are scored.
                record = dict(case_id=case['id'], doc_type=case['doc_type'], task_id=task_id, run_id=task['run_id'],
                    result_revision=task['result_revision'], status=task['status'], error_code=error_code, measured=True,
                    upload_to_result_seconds=wall, result_http_status=response.status_code, attempts=len(raw_attempts),
                    model_calls=sum(a.get('inference_performed', True) for a in raw_attempts),
                    cache_hits=sum(a.get('cache_hit', False) for a in raw_attempts),
                    page_count=len(pages), pending_regions=sum(r.get('status') != 'recognized' for p in pages for r in p.get('regions', []) if r.get('extraction_method') == 'ocr'),
                    **metrics)
                extracted = result.get('fields', []) + result.get('items', [])
                record['uncalibrated_confidence_valid'] = all(f.get('confidence') is None and f.get('confidence_method') == 'unavailable' for f in extracted) if result else None
                record['review_contract_valid'] = review_contract_valid(extracted, {f['key'] for f in case.get('fields', []) if f['required']}) if result else None
                tasks.append(record)
                active = None
                for index, attempt in enumerate(raw_attempts, 1):
                    prediction = attempt.get('prediction') or {}
                    attempts.append(dict(case_id=case['id'], run_id=task['run_id'], index=index,
                        **{k: attempt.get(k) for k in ('page_index', 'region_id', 'bbox', 'model', 'model_revision', 'task', 'attempt', 'status', 'error_code', 'input_sha256', 'transform', 'elapsed_seconds', 'timeout_seconds', 'max_new_tokens', 'generation_timeout_seconds', 'cache_hit', 'inference_performed', 'reused_from_region_id', 'reused_from_attempt')},
                        **{k: prediction.get(k) for k in ('recognition_seconds', 'output_tokens', 'termination_reason', 'gpu_peak_allocated_gib', 'gpu_peak_reserved_gib')}))
                (out / 'private' / (case['id'] + '.enc')).write_bytes(vault.pack(dict(result=result, pages=pages, attempts=raw_attempts)))
                for filename, rows in [('tasks', tasks), ('fields', fields), ('attempts', attempts)]:
                    csv_file(out / (filename + '.csv'), rows)
                save(out / 'tasks.json', tasks)
                print(json.dumps(dict(case_id=case['id'], status=task['status'], seconds=round(wall, 3))), flush=True)
                if case['id'] == 'synthetic-pdf' and raw_attempts:
                    raise ProbeError('NATIVE_PDF_DID_NOT_BYPASS_OCR')
                if case['id'] == 'synthetic-image' and not any(a.get('model') == 'glm_ocr' for a in raw_attempts):
                    raise ProbeError('SYNTHETIC_GLM_NOT_EXERCISED')
                if error_code in TIMEOUTS or any(a.get('error_code') in TIMEOUTS for a in raw_attempts):
                    report['stopped_after_failure'] = True
                    break
            report['infrastructure_status'] = 'passed'
            report['document_status'] = 'partial' if len(tasks) != len(cases) or any(t['status'] in {'FAILED', 'REJECTED', 'CANCELLED'} for t in tasks) else 'passed'
            report['status'] = 'partial' if report['document_status'] == 'partial' else 'passed'
    except Exception as error:
        report['failure_code'] = str(error) if isinstance(error, ProbeError) else 'PROBE_FAILED'
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
            report['owned_processes'], report['cleanup_wait_seconds'] = owned.wait_all(timeout=5)
            if any(not row['signaled'] for row in report['owned_processes']) or report.get('close_error') or report.get('observer_error'):
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
        # If transport/probe failure interrupted observation, retain the submitted case's denominator.
        if active:
            case = active['case']
            try:
                with closing(sqlite3.connect((out / 'private/data/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as database:
                    identity = database.execute('SELECT run_id,revision FROM tasks WHERE id=?', (active['task_id'],)).fetchone()
                result, pages, raw_attempts = published(out, active['task_id'], identity[0], identity[1])
                (out / 'private' / (case['id'] + '.enc')).write_bytes(vault.pack(dict(result=result, pages=pages, attempts=raw_attempts)))
            except Exception:
                result, pages = {}, []
            field_rows, metrics = score_case(case, result, pages)
            fields.extend(field_rows)
            tasks.append(dict(case_id=case['id'], doc_type=case['doc_type'], task_id=active['task_id'],
                              measured=True, status='PROBE_INTERRUPTED', upload_to_result_seconds=None,
                              elapsed_until_interruption_seconds=time.monotonic() - active['start'], **metrics))
        report['planned_cases'], report['recorded_cases'] = len(cases), len(tasks)
        for case in cases:
            if any(t['case_id'] == case['id'] for t in tasks):
                continue
            unrun, metrics = score_case(case, None, [])
            fields.extend({**row, 'outcome': 'not_run'} for row in unrun)
            tasks.append(dict(case_id=case['id'], doc_type=case['doc_type'], status='NOT_RUN', measured=False,
                              **{**metrics, 'field_accuracy': None, 'missing': 0, 'required_reference_missing': None, 'runtime_required_missing': None}))
        if protocol:
            report['provenance_unchanged'] = all((ROOT / p).is_file() and digest((ROOT / p).read_bytes()) == sha
                for group in ('code_hashes', 'source_hashes') for p, sha in protocol[group].items())
            if not report['provenance_unchanged']:
                report.update(status='failed', infrastructure_status='failed', failure_code='PROVENANCE_CHANGED')
        for filename, rows in [('tasks', tasks), ('fields', fields), ('attempts', attempts)]:
            csv_file(out / (filename + '.csv'), rows)
        save(out / 'tasks.json', tasks)
        report['elapsed_seconds'] = time.monotonic() - began
        save(out / 'summary.json', report)
    return 0 if report['status'] in {'passed', 'partial'} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8783)
    parser.add_argument('--mode', choices=['single_resident', 'dual_resident'], default='single_resident')
    parser.add_argument('--medical-all', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise ProbeError('INVALID_PORT')
        if args.serve:
            serve(args.output, args.port)
            return 0
        out = isolated_output(args.output)
        if args.prepare_only:
            _, cases, _ = prepare(out, mode=args.mode, medical_all=args.medical_all)
            print(json.dumps(dict(status='prepared', cases=len(cases))), flush=True)
            return 0
        return run(out, args.port, mode=args.mode, medical_all=args.medical_all)
    except Exception as error:
        print(json.dumps(dict(status='failed', code=str(error) if isinstance(error, ProbeError) else 'PROBE_FAILED')), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
