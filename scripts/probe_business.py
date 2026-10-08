"""Serial HTTP acceptance through the real launcher; reports contain no source text."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.winjob import JobProcess
from ocr_app.storage import Storage
from ocr_app.auth import Accounts
from ocr_app.db import open_database
from sqlalchemy import text
import httpx
import fitz
import psutil
from PIL import Image, ImageDraw, ImageFont
from probe_runtime import OwnedProcesses


def synthetic(out):
    lines = ['毕业证书', '姓名：测试样本', '性别：男', '学校名称：示例大学', '专业：计算机科学',
             '学历层次：本科', '毕业日期：2026年6月30日', '证书编号：123456202605000001']
    doc = fitz.open()
    page = doc.new_page(width=700, height=900)
    for index, line in enumerate(lines):
        page.insert_text((50, 80 + index * 65), line, fontname='china-s', fontsize=22)
    doc.save(out / 'synthetic-diploma.pdf')
    doc.close()
    image = Image.new('RGB', (1000, 1200), 'white')
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 40)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((70, 80 + index * 100), line, font=font, fill='black')
    image.save(out / 'synthetic-diploma.png')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--port', type=int, default=8767)
    ap.add_argument('--sample', action='append', default=[], help='DOC_TYPE=path; source files remain untouched')
    ap.add_argument('--browser', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    synthetic(out)
    records, attempt_records, owned = [], [], OwnedProcesses()
    process = None
    engine = None
    began = time.monotonic()
    report = dict(status='failed', scope='phase2 integration smoke; not an accuracy benchmark or HR hardware qualification')
    try:
        process = JobProcess([sys.executable, '-u', '-X', 'utf8', str(ROOT / 'backend/launch.py'),
                              '--no-browser', '--port', str(args.port)], cwd=ROOT)
        def drain(stream):
            for _ in stream:
                pass
        for stream in (process.stdout, process.stderr):
            threading.Thread(target=drain, args=(stream,), daemon=True).start()
        client = httpx.Client(base_url=f'http://127.0.0.1:{args.port}', timeout=30)
        for _ in range(600):
            if process.poll() is not None:
                raise RuntimeError('LAUNCHER_EXITED')
            try:
                health = client.get('/health').json()
                if 'http_ready_seconds' not in report:
                    report['http_ready_seconds'] = time.monotonic() - began
                if health.get('runtime', {}).get('state') == 'ready':
                    break
            except httpx.TransportError:
                pass
            time.sleep(.25)
        else:
            raise TimeoutError('MODEL_START_TIMEOUT')
        report.update(model_ready_seconds=time.monotonic()-began, health=health)
        owned.remember(psutil.Process(process.pid), 'launcher')
        for child in psutil.Process(process.pid).children(recursive=True):
            owned.remember(child)
        storage = Storage(ROOT / '.runtime/data')
        key = Accounts(storage).current_key()
        client.headers['X-API-Key'] = key
        assert client.get('/api/v1/auth/me').status_code == 200
        engine = open_database(ROOT / '.runtime/data', migrate=False)
        if args.browser:
            completed = subprocess.run(['node', str(ROOT / 'scripts/probe_browser.cjs')],
                input=json.dumps(dict(url=str(client.base_url), key=key, output=str(out),
                                      file=str(out / 'synthetic-diploma.pdf'))),
                text=True, encoding='utf-8', capture_output=True, timeout=120)
            # Browser output is intentionally an aggregate assertion result only.
            (out / 'browser-status.json').write_text(completed.stdout, encoding='utf-8')
            if completed.returncode:
                raise RuntimeError('BROWSER_ACCEPTANCE_FAILED')
        samples = [('synthetic-pdf', 'DIPLOMA', out / 'synthetic-diploma.pdf'),
                   ('synthetic-image', 'DIPLOMA', out / 'synthetic-diploma.png')]
        samples.extend((f'real-{i+1}', value.split('=', 1)[0], Path(value.split('=', 1)[1]))
                       for i, value in enumerate(args.sample))
        for alias, doc_type, path in samples:
            start = time.monotonic()
            upload = client.post('/api/v1/batches', data={'doc_type_hint': doc_type},
                                 files=[('files', (f'{alias}{path.suffix}', path.read_bytes(), 'application/octet-stream'))])
            assert upload.status_code == 202, (alias, upload.status_code)
            task_id = upload.json()['task_ids'][0]
            for _ in range(430):
                task = client.get('/api/v1/tasks/' + task_id).json()
                if task['status'] in {'NEED_REVIEW', 'FAILED', 'CANCELLED', 'REJECTED', 'COMPLETED'}:
                    break
                time.sleep(.5)
            else:
                raise TimeoutError('TASK_POLL_TIMEOUT')
            result_response = client.get('/api/v1/tasks/' + task_id + '/result')
            result = result_response.json() if result_response.status_code == 200 else {}
            with engine.connect() as connection:
                attempts = [storage.unpack(row[0]) for row in connection.execute(text(
                    'SELECT payload_enc FROM attempts WHERE run_id=:id'), {'id': task['run_id']})]
            fields = result.get('fields', [])
            for attempt in attempts:
                prediction = attempt.get('prediction', {})
                attempt_records.append(dict(alias=alias, run_id=task['run_id'], page=attempt.get('page_index'),
                    region_id=attempt.get('region_id'), model=attempt.get('model'), task=attempt.get('task'),
                    attempt=attempt.get('attempt'), model_revision=attempt.get('model_revision'),
                    elapsed_seconds=attempt.get('elapsed_seconds'), recognition_seconds=prediction.get('recognition_seconds'),
                    output_tokens=prediction.get('output_tokens'), termination_reason=prediction.get('termination_reason'),
                    error_code=attempt.get('error_code'), accuracy=None))
            record = dict(alias=alias, doc_type=doc_type, task_id=task_id, run_id=task['run_id'],
                status=task['status'], error_code=(task.get('error') or {}).get('code'),
                elapsed_seconds=round(time.monotonic()-start, 3), page_count=task['page_count'],
                attempts=len(attempts), fields_with_value=sum(f.get('value') is not None for f in fields),
                total_fields=len(fields), medical_items=len(result.get('items', [])),
                truncated_attempts=sum(a.get('prediction', {}).get('termination_reason') in {'token_limit', 'repetition_stop'} for a in attempts),
                accuracy=None)
            records.append(record)
            (out / 'tasks.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            print(json.dumps(record), flush=True)
        assert records[0]['attempts'] == 0, 'RELIABLE_PDF_MUST_BYPASS_OCR'
        assert records[1]['attempts'] > 0, 'IMAGE_MUST_USE_OCR'
        report['infrastructure_status'] = 'passed'
        report['document_failures'] = sum(row['status'] in {'FAILED', 'REJECTED', 'CANCELLED'} for row in records)
        report['status'] = 'partial' if report['document_failures'] else 'passed'
    except Exception as error:
        report['failure_type'] = type(error).__name__
        # Only our fixed error identifiers cross into the report.
        if str(error) in {'LAUNCHER_EXITED', 'MODEL_START_TIMEOUT', 'BROWSER_ACCEPTANCE_FAILED',
                          'TASK_POLL_TIMEOUT', 'RELIABLE_PDF_MUST_BYPASS_OCR', 'IMAGE_MUST_USE_OCR'}:
            report['failure_code'] = str(error)
    finally:
        if process:
            process.close()
            rows, duration = owned.wait_all()
            report.update(owned_processes=rows, exit_wait_seconds=duration)
            if not all(row['signaled'] for row in rows):
                report['status'] = 'failed'
        owned.close()
        if engine:
            engine.dispose()
        report['elapsed_seconds'] = time.monotonic()-began
        (out / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if records:
            with (out / 'tasks.csv').open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
        if attempt_records:
            with (out / 'attempts.csv').open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(attempt_records[0]))
                writer.writeheader()
                writer.writerows(attempt_records)
        print(json.dumps({'status': report['status'], 'elapsed_seconds': report['elapsed_seconds']}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
