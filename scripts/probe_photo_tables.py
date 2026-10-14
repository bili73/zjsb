"""Serial, single-resident photo-table qualification. No production database access.

References belong to an independent scorer and must never be passed to this probe.
Outputs containing source pixels or OCR text are encrypted with Storage.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def require_idle():
    import psutil
    with socket.socket() as connection:
        if connection.connect_ex(('127.0.0.1', 8765)) == 0:
            raise RuntimeError('STOP_IDLE_SERVICE_BEFORE_PROBE')
    for process in psutil.process_iter(['pid', 'cmdline']):
        command = ' '.join(process.info['cmdline'] or []).replace('\\', '/').lower()
        if process.pid != os.getpid() and any(name in command for name in ('backend/model_worker.py', 'backend/runtime_worker.py', 'backend/launch.py')):
            raise RuntimeError('EXISTING_OCR_PROCESS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', choices=['paddleocr_vl', 'glm_ocr'], default='paddleocr_vl')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    paths = sorted(p for p in args.source.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png'})
    if not paths:
        raise ValueError('NO_PHOTOS')
    require_idle()
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(args.out.resolve() / 'diagnostics')
    from PIL import Image, ImageOps
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.image_preprocessing import prepare_image
    from ocr_app.storage import Storage
    from ocr_app.table_recognition import candidate_image, decode_table_output, locate_table_candidates, nearby_text
    vault = Storage(args.out / 'private/data')
    watched = {p: digest(p.read_bytes()) for p in paths}
    code_paths = [Path(__file__), ROOT/'backend/ocr_app/table_recognition.py', ROOT/'backend/ocr_app/image_preprocessing.py', ROOT/'backend/ocr_app/table_format.py', ROOT/'backend/model_worker.py']
    code_hashes = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in code_paths}
    manifest, rows, private = [], [], []
    runtime = None
    lock = (ROOT/'output/two-model-retest-gpu.lock').open('a+b')
    summary = dict(model=args.model, residency='single_resident', execution='serial', source_count=len(paths), code_hashes=code_hashes)
    def save():
        (args.out/'private/results.enc').write_bytes(vault.pack(private))
        (args.out/'private/manifest.enc').write_bytes(vault.pack(manifest))
        (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
        if rows:
            with (args.out/'cases.csv').open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
    try:
        import msvcrt
        if not lock.tell():
            lock.write(b'1'); lock.flush()
        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        require_idle()
        if not args.prepare_only:
            runtime = RuntimeClient(RuntimeConfig(args.out/'session', mode='single_resident'))
            began = time.monotonic(); runtime.start()
            while runtime.snapshot()['state'] == 'starting' and time.monotonic()-began < 260:
                time.sleep(.2)
            summary.update(startup_seconds=time.monotonic()-began, startup_state=runtime.snapshot())
            if runtime.snapshot()['state'] != 'ready':
                raise RuntimeError('RUNTIME_NOT_READY')
            print('single-resident runtime ready', flush=True)
        for index, path in enumerate(paths, 1):
            started = time.monotonic()
            content = path.read_bytes()
            with Image.open(io.BytesIO(content)) as opened:
                original = ImageOps.exif_transpose(opened).convert('RGB')
            corrected, decision = prepare_image(original)
            candidates = locate_table_candidates(corrected)
            snippets = nearby_text(corrected, candidates)
            preparation_seconds = time.monotonic()-started
            case = f'sample-{index:02}'
            variants = [('whole', corrected, None)]
            if candidates:
                crop, transform = candidate_image(corrected, candidates[0])
                variants.append(('region', crop, transform))
            manifest.append(dict(id=case, source=str(path), sha256=watched[path],
                                 original_ref=vault.put(content), prepared_ref=vault.put(png(corrected)),
                                 orientation=decision, candidates=candidates, snippets=snippets))
            for variant, pixels, transform in variants:
                payload = png(pixels); prediction = {}; error = None; tables = []
                began = time.monotonic()
                if runtime:
                    try:
                        prediction = runtime.request('recognize', wait=185, model=args.model,
                            image_base64=base64.b64encode(payload).decode('ascii'), task='table',
                            timeout=max(1., 180-preparation_seconds), max_new_tokens=4096,
                            generation_timeout_seconds=80.)
                        tables = decode_table_output(prediction['text'])
                    except Exception as exc:
                        error = getattr(exc, 'code', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
                elapsed = time.monotonic()-began
                row = dict(sample=case, variant=variant, model=args.model, input_sha256=watched[path],
                           inference_input_sha256=digest(payload), preparation_seconds=preparation_seconds,
                           call_seconds=elapsed, recognition_seconds=prediction.get('recognition_seconds'),
                           termination=prediction.get('termination_reason'), output_tokens=prediction.get('output_tokens'),
                           error_code=error, grids=len(tables), dimensions=';'.join(f'{len(t["rows"])}x{len(t["rows"][0])}' for t in tables))
                rows.append(row)
                private.append(dict(sample=case, variant=variant, image_ref=vault.put(payload), transform=transform, prediction=prediction, tables=tables, metrics=row))
                if runtime:
                    stats = runtime.request('statistics', wait=5)
                    if len(stats['model_pids']) > 1:
                        raise RuntimeError('RESIDENCY_VIOLATION')
                    summary['runtime_statistics'] = stats
                save()
                print(f'{case} {variant}: {elapsed:.2f}s, {row["termination"]}, {row["dimensions"]}, {error}', flush=True)
    finally:
        if runtime:
            runtime.close()
            summary['runtime_stopped'] = runtime.is_stopped()
        lock.close()
        summary['inputs_unchanged'] = all(digest(p.read_bytes()) == h for p, h in watched.items())
        summary['code_unchanged_during_probe'] = all(digest((ROOT/name).read_bytes()) == h for name, h in code_hashes.items())
        summary['completed_calls'] = len(rows)
        save()


if __name__ == '__main__':
    main()
