"""Application-side persistence, input admission and bounded worker supervision."""
import io
import re
import threading
from time import monotonic
from pathlib import Path, PureWindowsPath

from .auth import Accounts
from .db import open_database
from .storage import Storage
from .task_store import TaskError, TaskStore, SUPPORTED
from .runtime import RuntimeFailure
from .image_admission import ImageAdmissionError, validate_image


def validate_upload(data: bytes, name: str):
    """Decode in memory before storage; no multipart spooling or plaintext temp files."""
    import fitz
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    if not data or len(data) > 10 * 1024 * 1024:
        raise TaskError('FILE_TOO_LARGE', '单文件须非空且不超过10MB', 413)
    try:
        if data.startswith(b'%PDF-'):
            with fitz.open(stream=data, filetype='pdf') as document:
                if document.needs_pass or not 1 <= document.page_count <= 100:
                    raise ValueError('unreadable PDF')
                # Reject explicit authentication secrets even if mislabeled.
                for page in document:
                    if page.rect.is_empty or page.rect.width * page.rect.height * 4 > 40_000_000:
                        raise ValueError('oversized PDF page')
                    content = page.get_text()
                    if re.search(r'\b(?:CVV2?|CVN2|CVC2?|CID)\s*[:：]?\s*\d{3,4}\b', content, re.I):
                        raise TaskError('UNSAFE_CARD_INPUT', '请去除卡片安全码后再上传', 422)
                source_pages = document.page_count
            mime = 'application/pdf'
        else:
            with Image.open(io.BytesIO(data)) as image:
                mime = validate_image(image, 40_000_000)
                image.load()
                source_pages = 1
    except TaskError:
        raise
    except ImageAdmissionError as error:
        if error.code == 'DOCUMENT_LIMIT':
            raise TaskError('FILE_TOO_LARGE', '图片不超过4000万像素', 413) from error
        raise TaskError('UNSUPPORTED_FORMAT', '请使用单张JPG/PNG/HEIC或PDF；多图材料请转换为PDF', 415) from error
    except Exception as error:
        raise TaskError('DECODE_FAILED', '文件无法读取；请使用未加密的PDF或清晰图片', 422) from error
    return dict(data=data, name=PureWindowsPath(name.replace('/', '\\')).name[:200], mime=mime,
                actual_source_page_count=source_pages)


def prepare_uploads(files, doc_type, runtime):
    """Decode before storage; recognize each accepted photo in its own queued task."""
    prepared = []
    for data, name in files:
        file = validate_upload(data, name)
        if doc_type == 'BANK_CARD' and file['mime'] == 'application/pdf':
            raise TaskError('UNSUPPORTED_FORMAT', '银行卡请上传单张JPG/PNG/HEIC照片；不接收PDF', 415)
        prepared.append(file)
    if sum(len(file['data']) for file in prepared) > 50 * 1024 * 1024:
        raise TaskError('FILE_TOO_LARGE', '处理后的单批材料超过50MB，请减少文件数量', 413)
    return prepared


class Business:
    def __init__(self, root: Path, logger=None, key=None):
        self.root, self.logger = Path(root), logger
        self.storage = Storage(self.root, key)
        self.engine = open_database(self.root)
        self.store = TaskStore(self.engine, self.storage, logger)
        self.accounts = Accounts(self.storage, self.engine)
        self.stop_event = threading.Event()
        self.monitor = None
        self.watchdog_error_id = None

    def prepare(self):
        # Launcher has acquired the exclusive lifetime lock before reaching this point.
        self.store.recover()
        self.store.cleanup()
        self.store.cleanup_orphans()

    def watch(self, runtime):
        def supervise():
            first_seen = {}
            while not self.stop_event.wait(.5):
                try:
                    active = self.store.active()
                    if not runtime.is_alive():
                        if active:
                            runtime.close(graceful=False)
                            self.store.recover()
                        continue
                    observed = monotonic()
                    identities = {(task['id'], task['run_id'], task['active_started_at']) for task in active}
                    first_seen = {key: value for key, value in first_seen.items() if key in identities}
                    for task in active:
                        key = (task['id'], task['run_id'], task['active_started_at'])
                        deadline = first_seen.setdefault(key, observed) + 181
                        if observed >= deadline:
                            stopped = self.store.timeout_run(task, deadline, lambda: runtime.stop_task(task))
                            if stopped and self.logger:
                                self.logger.event('watchdog_timeout', task_id=task['id'], run_id=task['run_id'])
                            if stopped:
                                break
                except Exception as error:
                    if self.logger:
                        self.watchdog_error_id = self.logger.exception('pipeline_failed', error)
                    if isinstance(error, RuntimeFailure) and error.code == 'SUPERVISION_FAILED':
                        # Unconfirmed cleanup cannot authorize DB recovery or an
                        # endless loop of retries against a failed supervisor.
                        try:
                            runtime.close(graceful=False)
                        except Exception as close_error:
                            if self.logger:
                                self.logger.exception('runtime_close_failed', close_error)
                        return
        self.monitor = threading.Thread(target=supervise, name='task-watchdog', daemon=True)
        self.monitor.start()

    def close(self):
        self.stop_event.set()
        if self.monitor:
            self.monitor.join(timeout=32)
            if self.monitor.is_alive():
                raise TimeoutError('Watchdog shutdown not confirmed')
        self.engine.dispose()
