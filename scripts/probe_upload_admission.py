"""CPU-only Edge acceptance through real upload routes, using synthetic inputs.

No launcher, RuntimeClient, model imports, production storage or real materials.
Each run retains its own attempt directory, including failed measurements.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tests'))


class FakeRuntime:
    def __init__(self):
        self.alive = True
        self.started = self.closed = self.requests = 0

    def start(self):
        self.started += 1

    def close(self, graceful=True):
        self.closed += 1
        self.alive = False

    def is_alive(self):
        return self.alive

    def snapshot(self):
        return dict(configured_mode='dual_resident', effective_mode='ocr_unavailable',
                    state='degraded', models=dict(glm_ocr='unloaded', paddleocr_vl='unloaded'), reason_code=None)

    def request(self, *args, **kwargs):
        self.requests += 1
        raise AssertionError('CPU_PROBE_MUST_NOT_REQUEST_MODEL')


def fixture_cases():
    from PIL import Image
    from hdr_jpeg_fixtures import make_mpo

    def image_bytes(fmt, color='white', **options):
        stream = io.BytesIO()
        Image.new('RGB', (64, 48), color).save(stream, format=fmt, **options)
        return stream.getvalue()

    jpeg = image_bytes('JPEG')
    apng = image_bytes('PNG', save_all=True, append_images=[Image.new('RGB', (64, 48), 'black')], duration=100, loop=0)
    unknown = make_mpo(None)

    def file(name, data, mime='image/jpeg'):
        return dict(name=name, mime=mime, base64=base64.b64encode(data).decode('ascii'), sha256=hashlib.sha256(data).hexdigest())

    return [
        dict(case_id='ordinary-jpeg', files=[file('synthetic-normal.jpg', jpeg)], expected_status=202),
        dict(case_id='apple-hdr', files=[file('synthetic-apple.jpg', make_mpo('apple'))], expected_status=202),
        dict(case_id='iso-hdr', files=[file('synthetic-iso.jpg', make_mpo('iso'))], expected_status=202),
        dict(case_id='adobe-hdr', files=[file('synthetic-adobe.jpg', make_mpo('adobe'))], expected_status=202),
        dict(case_id='unknown-mpo', files=[file('synthetic-unknown.jpg', unknown)], expected_status=415, expected_code='UNSUPPORTED_FORMAT'),
        dict(case_id='animated-png', files=[file('synthetic-animated.png', apng, 'image/png')], expected_status=415, expected_code='UNSUPPORTED_FORMAT'),
        dict(case_id='disguised-bmp', files=[file('synthetic-bmp.jpg', image_bytes('BMP'))], expected_status=415, expected_code='UNSUPPORTED_FORMAT'),
        dict(case_id='broken-jpeg', files=[file('synthetic-broken.jpg', b'SYNTHETIC_UNDECODABLE_BYTES')], expected_status=422, expected_code='DECODE_FAILED'),
        dict(case_id='atomic-mixed', files=[file('synthetic-valid.jpg', image_bytes('JPEG', 'blue')), file('synthetic-unknown.jpg', unknown)], expected_status=415, expected_code='UNSUPPORTED_FORMAT'),
    ]


def browser_case(payload):
    # The browser and its descendants are killed even if the Node runner times out.
    from ocr_app.winjob import JobProcess
    process = JobProcess(['node', str(ROOT / 'scripts/probe_upload_admission_browser.cjs')], cwd=ROOT)
    chunks = []
    stdout = threading.Thread(target=lambda: chunks.append(process.stdout.read()), daemon=True)
    stderr = threading.Thread(target=lambda: process.stderr.read(), daemon=True)
    stdout.start()
    stderr.start()
    try:
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        code = process.wait(timeout=100)
    finally:
        process.close()
        stdout.join(timeout=5)
        stderr.join(timeout=5)
    if stdout.is_alive() or stderr.is_alive():
        raise RuntimeError('BROWSER_READER_CLEANUP_FAILED')
    try:
        result = json.loads(''.join(chunks))
    except (ValueError, TypeError):
        result = dict(status='failed', failure_code='BROWSER_REPORT_INVALID')
    result['owned_browser_tree_closed'] = True
    return code, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'output/upload-admission-browser-20261008-v1')
    args = parser.parse_args()
    parent = args.output.resolve()
    if not parent.is_relative_to((ROOT / 'output').resolve()):
        raise ValueError('OUTPUT_MUST_BE_ISOLATED')
    parent.mkdir(parents=True, exist_ok=True)
    index = 1
    while (parent / f'attempt-{index:03}').exists():
        index += 1
    out = parent / f'attempt-{index:03}'
    out.mkdir()
    report = dict(status='running', scope='Real authenticated API, multipart admission and Edge UI; synthetic fixtures; FakeRuntime only; no OCR accuracy or production runtime claim', cases=[])
    summary = out / 'summary.json'

    def save():
        summary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    business = runtime = server = thread = sock = None
    began = time.monotonic()
    try:
        from ocr_app.api import create_app
        from ocr_app.business import Business
        import uvicorn
        cases = fixture_cases()
        business = Business(out / 'private/data', key=secrets.token_bytes(32))
        business.accounts.accounts[0]['display_name'] = '合成验收账号'
        key = business.accounts.current_key()
        runtime = FakeRuntime()
        app = create_app(runtime, ROOT / 'frontend/dist', out / 'private/session', business=business)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_config=None, log_level='critical'))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), name='synthetic-upload-http', daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not server.started:
            raise RuntimeError('ISOLATED_HTTP_START_FAILED')
        report['provenance'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            'scripts/probe_upload_admission.py', 'scripts/probe_upload_admission_browser.cjs',
            'tests/hdr_jpeg_fixtures.py', 'backend/ocr_app/business.py', 'backend/ocr_app/documents.py',
            'backend/ocr_app/image_admission.py', 'backend/ocr_app/pipeline.py', 'backend/ocr_app/diagnostics.py')}
        report['provenance'].update({path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in sorted((ROOT / 'frontend/dist').rglob('*')) if path.is_file()})
        for case in cases:
            before = (len(business.store.tasks()), len(list(business.storage.blobs.glob('*.bin'))))
            payload = dict(case, url=f'http://127.0.0.1:{port}', key=key, output=str(out))
            row = {key: value for key, value in case.items() if key != 'files'}
            row['input_sha256'] = [file['sha256'] for file in case['files']]
            report['cases'].append(row)
            save()
            code, result = browser_case(payload)
            # Browser emits only fixed codes, booleans/counts and opaque IDs; no raw errors.
            row['browser'] = result
            after = (len(business.store.tasks()), len(list(business.storage.blobs.glob('*.bin'))))
            expected_delta = len(case['files']) if case['expected_status'] == 202 else 0
            row['task_delta'], row['encrypted_blob_delta'] = (after[i] - before[i] for i in range(2))
            row['persistence_correct'] = row['task_delta'] == row['encrypted_blob_delta'] == expected_delta
            row['status'] = 'passed' if code == 0 and result.get('status') == 'passed' and row['persistence_correct'] else 'failed'
            save()
        tasks = business.store.tasks()
        report['final_task_count'] = len(tasks)
        report['all_tasks_queued'] = all(task['status'] == 'QUEUED' for task in tasks)
        report['all_blobs_encrypted'] = all(path.read_bytes().startswith(b'OCR1') for path in business.storage.blobs.glob('*.bin'))
        expected_hashes = sorted(file['sha256'] for case in cases if case['expected_status'] == 202 for file in case['files'])
        report['expected_task_count'] = len(expected_hashes)
        stored_hashes = sorted(hashlib.sha256(business.storage.decrypt(path.read_bytes())).hexdigest() for path in business.storage.blobs.glob('*.bin'))
        report['accepted_original_hashes_preserved'] = stored_hashes == expected_hashes
        report['model_request_count'] = runtime.requests
        report['status'] = 'passed' if all(row['status'] == 'passed' for row in report['cases']) and len(tasks) == report['expected_task_count'] and report['all_tasks_queued'] and report['all_blobs_encrypted'] and report['accepted_original_hashes_preserved'] and runtime.requests == 0 else 'failed'
    except Exception as error:
        report.update(status='failed', failure_code='CPU_ADMISSION_PROBE_FAILED', failure_type=type(error).__name__)
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
        if sock:
            sock.close()
        if business and (not thread or not thread.is_alive()):
            business.close()
        report['http_thread_closed'] = thread is None or not thread.is_alive()
        report['runtime_closed'] = runtime is None or not runtime.is_alive()
        report['watchdog_closed'] = business is None or business.monitor is None or not business.monitor.is_alive()
        report['elapsed_seconds'] = round(time.monotonic() - began, 3)
        if not all(report[key] for key in ('http_thread_closed', 'runtime_closed', 'watchdog_closed')):
            report['status'] = 'failed'
        save()
    print(json.dumps(dict(status=report['status'], cases=len(report['cases']), passed=sum(row.get('status') == 'passed' for row in report['cases']), attempt=index)))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
