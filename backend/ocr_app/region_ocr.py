"""Operator-selected transcription; no task/result writes or plaintext files."""
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time

from PIL import Image

from .doc_profiles import profile
from .preview import corrected_preview
from .task_store import TaskError
from .winjob import JobProcess

_slot = threading.Lock()
_cleanup_failed = False
MAX_PIXELS = 2_000_000
TIMEOUT_SECONDS = 10


def crop_region(data, bbox):
    if (not isinstance(bbox, list) or len(bbox) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox) or
            bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise TaskError('INVALID_REQUEST', '请选择有效的文字区域', 422)
    with Image.open(BytesIO(data)) as image:
        box = (math.floor(bbox[0] * image.width), math.floor(bbox[1] * image.height),
               math.ceil(bbox[2] * image.width), math.ceil(bbox[3] * image.height))
        width, height = box[2] - box[0], box[3] - box[1]
        if width < 8 or height < 8 or width * height > MAX_PIXELS:
            raise TaskError('INVALID_REQUEST', '请框选文字值，选区边长至少8像素、面积不超过200万像素', 422)
        target = BytesIO()
        image.crop(box).convert('RGB').save(target, format='PNG')
        return target.getvalue()


def _run_crop(data):
    """Exchange bounded binary data; supervise the virtualenv redirector and its tree."""
    global _cleanup_failed
    deadline = time.monotonic() + TIMEOUT_SECONDS
    args = [sys.executable, str(Path(__file__).with_name('region_ocr_worker.py'))]
    process = JobProcess(args)
    finished = threading.Event()
    output = bytearray()
    errors = []

    def exchange():
        try:
            pending = memoryview(data)
            while pending:
                written = process.stdin.buffer.write(pending)
                if not written:
                    raise OSError('worker stdin closed')
                pending = pending[written:]
            process.stdin.close()
            while len(output) <= 32768:
                chunk = process.stdout.buffer.read(min(4096, 32769 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    def discard_stderr():
        try:
            while process.stderr.buffer.read(4096):
                pass
        except (OSError, ValueError):
            pass

    io_thread = threading.Thread(target=exchange, daemon=True)
    err_thread = threading.Thread(target=discard_stderr, daemon=True)
    try:
        err_thread.start()
        io_thread.start()
        if not finished.wait(max(0, deadline - time.monotonic())):
            raise TimeoutError('region worker exceeded execution budget')
        if errors:
            raise errors[0]
        if len(output) > 32768:
            raise ValueError('oversized worker output')
        code = process.wait(max(0, deadline - time.monotonic()))
        return subprocess.CompletedProcess(args, code, bytes(output))
    finally:
        try:
            process.close()  # Includes whole-Job exit confirmation, even after normal root exit.
        except Exception:
            _cleanup_failed = True
            raise TaskError('REGION_OCR_UNAVAILABLE', '框选识别进程回收未确认，请重启后端后再试；当前可手工填写', 503) from None
        finally:
            for thread in (io_thread, err_thread):
                if thread.ident is not None:
                    thread.join(timeout=.2)


def recognize_crop(data):
    if not _slot.acquire(blocking=False):
        raise TaskError('REGION_OCR_BUSY', '框选识别正在处理中，请稍后再试', 429)
    try:
        if _cleanup_failed:
            raise TaskError('REGION_OCR_UNAVAILABLE', '框选识别进程回收未确认，请重启后端后再试；当前可手工填写', 503)
        try:
            completed = _run_crop(data)
        except TimeoutError:
            raise TaskError('REGION_OCR_TIMEOUT', '框选识别超时，请缩小选区重试或手工填写', 504) from None
        if completed.returncode != 0 or len(completed.stdout) > 32768:
            raise ValueError('invalid worker output')
        result = json.loads(completed.stdout)
        value, confidence = result['text'], result['confidence']
        if (not isinstance(value, str) or len(value) > 4096 or
                type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError('invalid OCR response')
        if not value.strip():
            raise TaskError('REGION_OCR_EMPTY', '选区没有读出文字，请重新框选或手工填写', 422)
        return dict(text=value, confidence=confidence)
    except TaskError:
        raise
    except Exception:
        raise TaskError('REGION_OCR_UNAVAILABLE', '框选识别暂不可用，请手工填写或稍后再试', 503) from None
    finally:
        _slot.release()


def transcribe_region(store, task_id, body, user, authorize):
    field_key = body.get('field_key')

    def verify(connection):
        authorize(connection)
        row = store._row(connection, task_id, user)
        store._expected(row, body['run_id'], body['expected_revision'])
        if field_key is not None:
            field = next((f for f in profile(row['doc_type']) if f['key'] == field_key), None)
            if not field or not field['editable'] or field['key'] == 'gender' or field['type'] == 'boolean':
                raise TaskError('INVALID_REQUEST', '该字段不支持框选补录', 422)
        if not row['result_enc']:
            raise TaskError('INVALID_STATE', '当前没有可查看的识别结果', 409)
        return row

    with store.engine.connect() as connection:
        verify(connection)
    data = corrected_preview(store, task_id, body['run_id'], body['expected_revision'], body['page'],
                             actor=user['user_id'], role=user['role'], user=user, authorize=authorize)
    result = recognize_crop(crop_region(data, body['bbox']))
    # A later login, edit, rerun or deletion must not receive old OCR content.
    with store.transaction() as connection:
        row = verify(connection)
        store._audit(connection, 'field_region_ocr', user['user_id'], row,
                     result_revision=body['expected_revision'], page=body['page'], field_key=field_key)
    return dict(result, task_id=task_id, run_id=body['run_id'], result_revision=body['expected_revision'],
                field_key=field_key, page=body['page'], bbox=body['bbox'])
