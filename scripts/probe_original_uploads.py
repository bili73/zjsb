"""CPU-only admission/API/primary-image regression on the authorized original folder.

No OCR model, production database, plaintext material copy or reference change.
Run only after the image admission helper and its tests have been finalized.
"""
import argparse
from contextlib import closing
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
import probe_current_pipeline as base

SOURCE = Path('F:/dingding/附件_20260728')
INVESTIGATION = ROOT / 'output/upload-admission-investigation-20261008-v1'


class FakeRuntime:
    """A healthy inert runtime: uploading must only create queued tasks."""
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
        return dict(configured_mode='dual_resident', effective_mode='dual_resident', state='ready',
                    models=dict(glm_ocr='ready', paddleocr_vl='ready'), reason_code=None)

    def request(self, *args, **kwargs):
        self.requests += 1
        raise AssertionError('MODEL_EXECUTION_FORBIDDEN')

    def stop_task(self, task):
        raise AssertionError('NO_ACTIVE_TASK_EXPECTED')


def safe_code(error):
    from ocr_app.task_store import TaskError
    from ocr_app.documents import DocumentError
    if isinstance(error, (TaskError, DocumentError)):
        return error.code
    if isinstance(error, base.ProbeError):
        return str(error)
    return 'PROBE_FAILED'


def code_hashes():
    files = [*ROOT.glob('backend/**/*.py'), Path(__file__).resolve(), ROOT / 'scripts/probe_current_pipeline.py']
    return {str(p.relative_to(ROOT)): base.digest(p.read_bytes()) for p in sorted(files)}


def primary_check(data):
    from PIL import Image, ImageOps
    from ocr_app.documents import decode_pages
    with Image.open(io.BytesIO(data)) as original:
        original.seek(0)
        expected = ImageOps.exif_transpose(original).convert('RGB')
    try:
        reference_hash = base.digest(expected.tobytes())
        generator = decode_pages(data)
        with closing(generator):
            first = next(generator)
            try:
                actual_hash = base.digest(first.image.tobytes())
                details = dict(page_index=first.index, rgb=first.image.mode == 'RGB',
                    width=first.image.width, height=first.image.height,
                    expected_primary_width=expected.width, expected_primary_height=expected.height,
                    actual_rgb_sha256=actual_hash, expected_rgb_sha256=reference_hash,
                    primary_pixels_equal=first.image.mode == 'RGB' and first.image.size == expected.size and actual_hash == reference_hash)
                second = next(generator, None)
                details['one_page'] = second is None
                if second is not None:
                    second.image.close()
                return details
            finally:
                first.image.close()
    finally:
        expected.close()


def run(out):
    from fastapi.testclient import TestClient
    from PIL import Image
    from sqlalchemy import text
    from ocr_app.api import create_app
    from ocr_app.business import Business, validate_upload
    from ocr_app.storage import Storage
    began = time.monotonic()
    results, uploads, sources, unavailable = [], [], [], []
    hashes = code_hashes()
    runtime = FakeRuntime()
    business = None
    report = dict(status='failed', scope='CPU upload admission and authenticated HTTP/storage/primary decode regression; no OCR, GPU, clinical accuracy or production database',
                  reference_files=34, expected_original_mpo=6, expected_hdr_http_images=7)
    vault = Storage(out / 'private/fixtures')
    try:
        previous = json.loads((INVESTIGATION / 'original-folder-results.json').read_text(encoding='utf-8'))
        expected = {r['alias']: r for r in previous['results']}
        by_hash = {r['sha256']: r for r in previous['results']}
        files = sorted(p for p in SOURCE.rglob('*') if p.is_file())
        if len(files) not in {33, 34} or len(expected) != 34 or len(by_hash) != 34:
            raise base.ProbeError('SOURCE_SET_CHANGED')
        report['available_files'] = len(files)
        mpo = []
        seen = set()
        for path in files:
            data = path.read_bytes()
            sha = base.digest(data)
            if sha not in by_hash or sha in seen:
                raise base.ProbeError('SOURCE_BYTES_CHANGED')
            seen.add(sha)
            alias = by_hash[sha]['alias']
            sources.append(dict(alias=alias,original_path=str(path),sha256=sha))
            row = dict(alias=alias,sha256=sha,byte_size=len(data),accepted=False,mime=None,validation_error=None)
            try:
                admitted = validate_upload(data, alias + path.suffix.lower())
                row.update(accepted=True,mime=admitted['mime'],raw_bytes_preserved=admitted['data'] == data)
            except Exception as error:
                row['validation_error'] = safe_code(error)
            results.append(row)
            # Pillow presents this one valid Adobe HDR/MP container as JPEG.
            # Keep the six originally visible MPOs plus this exact frozen alias.
            if expected[alias]['format'] == 'MPO' or alias == 'original-file-0032':
                mpo.append((alias, path))
            base.save(out / 'admission.json', results)
        unavailable = [dict(alias=r['alias'],status='not_available',prior_format=r['format'])
                       for r in previous['results'] if r['sha256'] not in seen]
        # The owner confirmed this one ordinary JPEG disappeared between the
        # investigation and CPU acceptance; retain the absence, never score it.
        if {r['alias'] for r in unavailable} - {'original-file-0003'}:
            raise base.ProbeError('SOURCE_SET_CHANGED')
        base.save(out / 'unavailable.json', unavailable)
        if len(mpo) != 7:
            raise base.ProbeError('HDR_HTTP_SET_CHANGED')
        # The default constructor generates a random DPAPI-protected encryption key
        # and random account credentials in this new isolated directory only.
        business = Business(out / 'private/data')
        business.prepare()
        app = create_app(runtime, out / 'missing-dist', out / 'session', business=business)
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
            headers = {'X-API-Key': business.accounts.current_key()}
            report['auth_verified'] = client.get('/api/v1/auth/me', headers=headers).status_code == 200
            if not report['auth_verified']:
                raise base.ProbeError('AUTH_FAILED')
            for alias, path in mpo:
                data = path.read_bytes()
                row = dict(alias=alias,sha256=base.digest(data),http_status=None,error_code=None,
                    encrypted_roundtrip_equal=False,encrypted_blob=False,raw_hash_equal=False,
                    task_queued=False,pages=None,one_page=False,primary_pixels_equal=False)
                try:
                    with Image.open(io.BytesIO(data)) as image:
                        row.update(original_format=image.format,original_frames=getattr(image, 'n_frames', 1))
                    response = client.post('/api/v1/batches', headers=headers, data={'doc_type_hint':'DIPLOMA'},
                        files=[('files', (alias + path.suffix.lower(), data, 'image/jpeg'))])
                    row['http_status'] = response.status_code
                    if response.status_code != 202:
                        row['error_code'] = response.json().get('code')
                    else:
                        task_ids = response.json()['task_ids']
                        if len(task_ids) != 1:
                            raise base.ProbeError('UPLOAD_TASK_COUNT_MISMATCH')
                        with business.engine.connect() as connection:
                            stored = connection.execute(text('SELECT input_ref,content_hash,status,meta_enc FROM tasks WHERE id=:id'),
                                {'id':task_ids[0]}).mappings().one()
                        raw = business.storage.read(stored['input_ref'])
                        ciphertext = business.storage.path(stored['input_ref']).read_bytes()
                        row.update(encrypted_roundtrip_equal=raw == data,
                            encrypted_blob=ciphertext.startswith(b'OCR1') and ciphertext != data,
                            raw_hash_equal=stored['content_hash'] == base.digest(data) == base.digest(raw),
                            task_queued=stored['status'] == 'QUEUED',mime=business.storage.unpack(stored['meta_enc'])['mime_type'])
                        # Decode exactly the bytes read back from controlled encrypted storage.
                        row.update(primary_check(raw))
                        row['pages'] = 1 if row['one_page'] else None
                except Exception as error:
                    row['error_code'] = safe_code(error)
                uploads.append(row)
                base.save(out / 'mpo-http.json', uploads)
        report['status'] = 'passed' if (
            len(results) == len(files) and all(r['accepted'] and r.get('raw_bytes_preserved') for r in results)
            and len(uploads) == 7 and all(r['http_status'] == 202 and r['error_code'] is None and all(r.get(k) for k in
                ('encrypted_roundtrip_equal','encrypted_blob','raw_hash_equal','task_queued','one_page','primary_pixels_equal','rgb')) for r in uploads)
            and runtime.requests == 0 and runtime.started == 1 and runtime.closed == 1) else 'failed'
    except Exception as error:
        report['failure_code'] = safe_code(error)
    finally:
        if business:
            business.close()
        (out / 'private/source-map.enc').write_bytes(vault.pack(sources))
        try:
            report['source_final_hashes_unchanged'] = len(sources) == report.get('available_files') and all(
                base.digest(Path(s['original_path']).read_bytes()) == s['sha256'] for s in sources) and {
                    p for p in SOURCE.rglob('*') if p.is_file()} == {Path(s['original_path']) for s in sources}
            report['code_hashes_unchanged'] = code_hashes() == hashes
        except Exception:
            report['source_final_hashes_unchanged'] = False
            report['code_hashes_unchanged'] = False
        if not report['source_final_hashes_unchanged'] or not report['code_hashes_unchanged']:
            report['status'] = 'failed'
        report.update(tested_files=len(results),admission_accepted=sum(r['accepted'] for r in results),
            reference_not_available=unavailable,
            mpo_http_tested=len(uploads),mpo_http_accepted=sum(r['http_status'] == 202 for r in uploads),
            mpo_primary_matches=sum(r['primary_pixels_equal'] for r in uploads),
            runtime_start_calls=runtime.started,runtime_close_calls=runtime.closed,model_requests=runtime.requests,
            elapsed_seconds=time.monotonic()-began)
        base.save(out / 'admission.json', results)
        base.save(out / 'unavailable.json', unavailable)
        base.save(out / 'mpo-http.json', uploads)
        base.save(out / 'provenance.json', dict(code_hashes=hashes,
            source_reference_sha256=base.digest((INVESTIGATION / 'original-folder-results.json').read_bytes())))
        base.save(out / 'summary.json', report)
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(base.isolated_output(args.output))
    except Exception as error:
        print(json.dumps(dict(status='failed',error_code=safe_code(error))),flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
