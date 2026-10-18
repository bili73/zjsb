"""Bounded, allowlisted diagnostics. Never serialize material, messages or locals."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sqlite3
import stat
import sys
import threading
import time
import traceback
import uuid
import zipfile
from tempfile import TemporaryFile
from datetime import datetime, timezone

from .diagnostic_messages import describe

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / '.runtime' / 'diagnostics'
MAX_BYTES = 10 * 1024 * 1024
FILE_COUNT = 5
RETENTION_SECONDS = 7 * 86400
APP_VERSION = '1.26.0'
LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}
OWNER = 'local-ocr-safe-diagnostics-v1'
COMPONENTS = {'bootstrap', 'launcher', 'api', 'client', 'runtime', 'model', 'collector', 'frontend'}
EVENTS = set('''event initialized bootstrap_started bootstrap_failed launcher_started launcher_failed
server_started server_failed storage_failed runtime_start_failed runtime_close_failed health_invalid
frontend_error export_completed export_failed spawn_started spawn_completed spawn_failed
reader_failed writer_failed protocol_failed stderr_drained request_started request_completed
request_failed request_timeout phase_changed model_failed model_loaded model_unloaded
close_started close_completed close_failed process_exited startup_started startup_completed
runtime_started runtime_failed runtime_stopped cleanup_failed storage_probe_failed
health_snapshot_failed gpu_lease_failed settings_failed server_stopped task_created task_claimed
task_stage task_completed task_cancelled task_interrupted task_expired request_completed request_failed
upload_rejected pipeline_failed watchdog_timeout migration_failed retention_failed batch_cleanup_failed'''.split())
ERROR_CODES = set('''SERVICE_BUSY OPERATION_THROTTLED REGION_OCR_BUSY REGION_OCR_TIMEOUT REGION_OCR_EMPTY REGION_OCR_UNAVAILABLE
RESOURCE_LIMIT MODEL_LOAD_FAILED MODEL_WARMUP_FAILED MODEL_PROCESS_EXITED
SUPERVISION_FAILED MODEL_REQUEST_TIMEOUT INPUT_INVALID INVALID_REQUEST RUNTIME_STARTING
RUNTIME_BUSY CUDA_UNAVAILABLE CONNECTION_FAILED INVALID_HEALTH DIAGNOSTICS_UNAVAILABLE
EXTRACT_TIMEOUT WORKER_INTERRUPTED DECODE_FAILED UNSUPPORTED_DOC_TYPE UNSUPPORTED_FORMAT FILE_TOO_LARGE
INTERNAL_ERROR RETENTION_VERSION_CONFLICT WORKBENCH_DEFAULT_VERSION_CONFLICT WORKBENCH_VERSION_CONFLICT RESULT_VERSION_CONFLICT INVALID_STATE FORBIDDEN_REVEAL
UNAUTHORIZED FORBIDDEN NOT_FOUND LOGIN_THROTTLED AUTH_NOT_CONFIGURED USERNAME_EXISTS ACCOUNT_PROTECTED
CURRENT_PASSWORD_INCORRECT SETTINGS_VERSION_CONFLICT DIAGNOSTICS_BUSY DIAGNOSTICS_UNAVAILABLE DIAGNOSTICS_RATE_LIMITED
CLIENT_ERROR NETWORK_ERROR REQUEST_TIMEOUT INVALID_RESPONSE
UNSAFE_CARD_INPUT CARD_ADMISSION_FAILED EXPORT_BLOCKED EXPORT_VALUE_TOO_LONG PREVIEW_MASK_UNAVAILABLE'''.split())
ENUMS = {
    'model': {'glm_ocr', 'paddleocr_vl', 'glm-ocr', 'paddleocr-vl'},
    'phase': {'loading', 'warming', 'ready', 'starting', 'stopping', 'recognize', 'unloaded', 'failed'},
    'operation': {'load', 'recognize', 'statistics', 'shutdown', 'stop_task', 'startup', 'close',
                  'audit', 'health', 'auth', 'account_list', 'account_create', 'account_update', 'account_delete',
                  'password_change', 'retention_read', 'retention_save', 'required_settings_read', 'required_settings_save',
                  'workbench_layout_read', 'workbench_layout_save', 'workbench_default_save', 'batch_list', 'batch_tasks',
                  'batch_delete', 'person_update', 'upload', 'classify', 'region_ocr', 'result', 'cancel', 'rerun',
                  'interface', 'catalogue', 'review', 'preview', 'export', 'diagnostics'},
    'http_method': {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'},
    'origin': {'vue', 'window', 'promise', 'http'},
    'frontend_exception_type': {'Error', 'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError', 'URIError', 'EvalError', 'DOMException'},
    'browser_event': {'javascript_error', 'resize_observer', 'opaque_script', 'promise_rejection', 'vue_error'},
    'database_error': {'missing_table', 'missing_column', 'busy', 'readonly', 'constraint', 'corrupt', 'other'},
    'configured_mode': {'dual_resident', 'single_resident'},
    'effective_mode': {'dual_resident', 'single_resident', 'ocr_unavailable'},
    'state': {'starting', 'ready', 'degraded', 'stopping'},
    'termination_reason': {'eos', 'token_limit', 'repetition_stop', 'time_limit'},
    'error_code': ERROR_CODES, 'reason_code': ERROR_CODES,
    'stage': {'BOOTSTRAP', 'QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING', 'PUBLISHING', 'CLEANUP'},
}
IDS = {'task_id', 'run_id', 'batch_id', 'page_id', 'region_id', 'request_id', 'process_instance_id', 'actor_id', 'client_error_id'}
NUMBERS = {'pid', 'child_pid', 'exit_code', 'duration_seconds', 'timeout_seconds', 'output_tokens',
           'stderr_characters', 'stderr_lines', 'page', 'region', 'errno', 'winerror', 'http_status',
           'load_seconds', 'warmup_seconds', 'recognition_seconds', 'elapsed_seconds', 'gpu_peak_allocated_gib',
           'gpu_peak_reserved_gib', 'gpu_allocated_gib', 'gpu_reserved_gib', 'rss_gib', 'warmup_tokens',
           'generation_timeout_seconds', 'max_new_tokens', 'queue_wait_seconds', 'frontend_line', 'frontend_column'}
EXCEPTION_TYPES = set('''Exception BaseException RuntimeError ValueError TypeError KeyError OSError
PermissionError FileNotFoundError FileExistsError TimeoutError MemoryError ImportError ModuleNotFoundError
BrokenPipeError UnicodeError UnicodeDecodeError JSONDecodeError AssertionError RuntimeFailure JobError TaskError DocumentError
OutOfMemoryError UnidentifiedImageError DecompressionBombError KeyboardInterrupt SystemExit
OperationalError IntegrityError ProgrammingError DatabaseError InterfaceError DataError InternalError
NotSupportedError StatementError DBAPIError'''.split())
FILE_PATTERN = re.compile(r'^ocrdiag-s_[0-9a-f]{24}-(?:' + '|'.join(sorted(COMPONENTS)) +
                          r')-[0-9]+-[0-9a-f]{32}\.jsonl(?:\.[1-4])?$')


def opaque_id(value, prefix='id_'):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    value = str(value)
    if re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value) and prefix == 'id_':
        return value
    if re.fullmatch(re.escape(prefix) + r'[0-9a-f]{24}', value):
        return value
    return prefix + hashlib.sha256(value.encode('utf-8', errors='replace')).hexdigest()[:24]


def safe_context(context):
    result = {}
    for key, value in context.items():
        if key in IDS and value is not None:
            result[key] = opaque_id(value)
        elif key == 'error_id' and isinstance(value, str) and re.fullmatch(r'e_[0-9a-f]{32}', value):
            result[key] = value
        elif key == 'model_revision' and isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
            result[key] = value
        elif key == 'frontend_build' and isinstance(value, str) and re.fullmatch(r'b_[A-Za-z0-9_-]{8,64}', value):
            result[key] = value
        elif key == 'sqlite_errorcode' and type(value) is int and 0 <= value < 2**31:
            result[key] = value
        elif key in ENUMS and (value is None or isinstance(value, str) and value in ENUMS[key]):
            result[key] = value
        elif key in NUMBERS and isinstance(value, (int, float)) and not isinstance(value, bool):
            if abs(value) <= 1e9 and math.isfinite(value):
                result[key] = value
    return result


def correlation_context(context):
    return {key: value for key, value in safe_context(context).items()
            if key in IDS or key in {'page', 'region', 'stage'}} if isinstance(context, dict) else {}


def _frame(frame):
    """Repository code only; never inspect source lines or frame locals."""
    try:
        relative = Path(frame.f_code.co_filename).resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        relative = ''
    if (relative.startswith(('backend/', 'scripts/')) and
            re.fullmatch(r'[A-Za-z_./-]+\.py', relative)):
        function = frame.f_code.co_name
        return relative, function if re.fullmatch(r'[A-Za-z_<>]{1,80}', function) else 'function'
    return 'external', 'external'


def _sqlite_context(error):
    if not isinstance(error, sqlite3.Error):
        return {}
    details = safe_context({'sqlite_errorcode': getattr(error, 'sqlite_errorcode', None)})
    primary = details.get('sqlite_errorcode', 0) & 0xff
    category = {
        sqlite3.SQLITE_BUSY: 'busy', sqlite3.SQLITE_LOCKED: 'busy', sqlite3.SQLITE_READONLY: 'readonly',
        sqlite3.SQLITE_CONSTRAINT: 'constraint', sqlite3.SQLITE_CORRUPT: 'corrupt', sqlite3.SQLITE_NOTADB: 'corrupt',
    }.get(primary, 'other')
    # Inspect only native SQLite prose for fixed prefixes; never retain any of it.
    if primary == sqlite3.SQLITE_ERROR:
        message = str(error)
        if message.startswith('no such table: '):
            category = 'missing_table'
        elif message.startswith('no such column: '):
            category = 'missing_column'
    return dict(details, database_error=category)


def safe_exception(error):
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 4:
        seen.add(id(error))
        frames = []
        for frame, line in traceback.walk_tb(error.__traceback__):
            file, function = _frame(frame)
            frames.append(dict(file=file, function=function, line=line))
        name = type(error).__name__
        entry = dict(type=name if name in EXCEPTION_TYPES else 'Exception', frames=frames[-16:])
        entry.update(safe_context({key: getattr(error, key, None) for key in ('errno', 'winerror')}))
        entry.update(_sqlite_context(error))
        chain.append(entry)
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return chain


def _warning():
    try:
        print('DIAGNOSTICS_UNAVAILABLE: technical diagnostics could not be saved.', file=sys.stderr, flush=True)
    except Exception:
        pass


def _regular(path):
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def severity(event, context, exceptional=False):
    status = context.get('http_status')
    if isinstance(status, int) and 400 <= status < 500:
        return 'WARNING'
    if event in {'storage_failed', 'storage_probe_failed', 'migration_failed', 'runtime_start_failed',
                 'runtime_failed', 'bootstrap_failed', 'launcher_failed', 'server_failed'}:
        return 'CRITICAL'
    if exceptional or event.endswith(('_failed', '_timeout', '_interrupted')) or event == 'frontend_error' or (isinstance(status, int) and status >= 500):
        return 'ERROR'
    if context.get('termination_reason') in {'token_limit', 'repetition_stop', 'time_limit'} or event == 'upload_rejected':
        return 'WARNING'
    if event == 'stderr_drained':
        return 'DEBUG'
    return 'INFO'


class DiagnosticLogger:
    def __init__(self, root, component, session_id=None):
        self.root = Path(root)
        self.component = component if isinstance(component, str) and component in COMPONENTS else 'runtime'
        self.session_id = opaque_id(session_id or uuid.uuid4().hex, 's_')
        self.instance = uuid.uuid4().hex
        self.path = self.root / f'ocrdiag-{self.session_id}-{self.component}-{os.getpid()}-{self.instance}.jsonl'
        self.lock = threading.Lock()
        self.available = True
        self.closed = False
        self.failure_at = None
        self.retry_at = 0
        configured = os.environ.get('OCR_LOG_LEVEL', 'ERROR').upper()
        self.minimum_level = LEVELS.get(configured, LEVELS['ERROR'])
        try:
            from .diagnostic_archive import safe_directory
            safe_directory(self.root)
            # Error-only operation must still detect an unwritable directory at startup.
            with TemporaryFile(dir=self.root) as probe:
                probe.write(b'0')
                probe.flush()
            self.event('initialized')
        except Exception:
            self._failed()

    def _failed(self):
        from .diagnostic_archive import atomic_json
        self.available = False
        self.failure_at = datetime.now(timezone.utc).isoformat()
        self.retry_at = time.monotonic() + 30
        try:
            atomic_json(self.root / ('failure-' + self.instance + '.json'),
                        dict(timestamp=self.failure_at, component=self.component, session_id=self.session_id))
        except Exception:
            pass
        _warning()

    def _write(self, record):
        if self.closed or LEVELS[record['level']] < self.minimum_level or (not self.available and time.monotonic() < self.retry_at):
            return
        try:
            from .diagnostic_archive import archive_file, locked
            encoded = (json.dumps(record, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
            with self.lock, locked(self.root):
                if self.path.exists() and not _regular(self.path):
                    raise OSError('Unsafe diagnostic file')
                if self.path.exists() and self.path.stat().st_size + len(encoded) > MAX_BYTES:
                    oldest = Path(str(self.path) + f'.{FILE_COUNT - 1}')
                    if oldest.exists():
                        archive_file(self.root, oldest)
                    for number in range(FILE_COUNT - 1, 0, -1):
                        source = self.path if number == 1 else Path(str(self.path) + f'.{number - 1}')
                        target = Path(str(self.path) + f'.{number}')
                        if source.exists():
                            if not _regular(source) or (target.exists() and not _regular(target)):
                                raise OSError('Unsafe diagnostic segment')
                            source.replace(target)
                with self.path.open('ab') as stream:
                    stream.write(encoded)
                    stream.flush()
                    if LEVELS[record['level']] >= LEVELS['ERROR']:
                        os.fsync(stream.fileno())
                self.available = True
                (self.root / ('failure-' + self.instance + '.json')).unlink(missing_ok=True)
        except Exception:
            self._failed()

    def _record(self, event, context):
        record = dict(owner=OWNER, version=1, app_version=APP_VERSION, level=severity(event, context),
                    record_id='l_' + uuid.uuid4().hex, timestamp=datetime.now(timezone.utc).isoformat(),
                    component=self.component, session_id=self.session_id, pid=os.getpid(),
                    process_instance_id=opaque_id(self.instance), event=event if isinstance(event, str) and event in EVENTS else 'event',
                    context=safe_context(context))
        record['description'] = describe(record['event'], record['context'])
        return record

    def event(self, event, **context):
        self._write(self._record(event, context))

    def exception(self, event, error, **context):
        error_id = 'e_' + uuid.uuid4().hex
        try:
            record = self._record(event, {**context, 'error_id': error_id})
            record['level'] = severity(event, context, exceptional=True)
            record['exceptions'] = safe_exception(error)
            self._write(record)
        except Exception:
            _warning()
        return error_id

    def close(self):
        self.closed = True


def init_diagnostics(root: Path, component: str, session_id: str | None = None):
    return DiagnosticLogger(root, component, session_id)


def session_diagnostics(session_dir, component):
    """Production sessions share the owned root; isolated tests/probes stay isolated."""
    session_dir = Path(session_dir)
    default = DEFAULT_ROOT if session_dir.parent == ROOT / '.runtime' else session_dir / 'diagnostics'
    root = Path(os.environ.get('OCR_DIAGNOSTICS_ROOT', str(default)))
    return init_diagnostics(root, component, os.environ.get('OCR_DIAGNOSTICS_SESSION', session_dir.name))


def _export_record(record):
    """Revalidate persisted data; a filename alone never authorizes raw copying."""
    if not isinstance(record, dict) or record.get('owner') != OWNER or record.get('version') != 1:
        return None
    if record.get('component') not in COMPONENTS or record.get('event') not in EVENTS:
        return None
    timestamp = record.get('timestamp')
    if not isinstance(timestamp, str) or not re.fullmatch(r'[0-9T:+.Z-]{20,40}', timestamp):
        return None
    result = {key: record[key] for key in ('owner', 'version', 'timestamp', 'component', 'event')}
    result.update(session_id=opaque_id(record.get('session_id'), 's_'),
                  process_instance_id=opaque_id(record.get('process_instance_id')))
    if type(record.get('pid')) is int and 0 < record['pid'] < 2**32:
        result['pid'] = record['pid']
    result['context'] = safe_context(record.get('context', {}) if isinstance(record.get('context'), dict) else {})
    level = record.get('level')
    result['level'] = level if isinstance(level, str) and level in LEVELS else severity(record['event'], result['context'], bool(record.get('exceptions')))
    version = record.get('app_version')
    result['app_version'] = version if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', version) else 'unknown'
    exceptions = []
    for error in record.get('exceptions', [])[:4] if isinstance(record.get('exceptions'), list) else []:
        if not isinstance(error, dict):
            continue
        entry = dict(type=error.get('type') if error.get('type') in EXCEPTION_TYPES else 'Exception', frames=[])
        entry.update(safe_context({key: error[key] for key in ('errno', 'winerror', 'sqlite_errorcode', 'database_error') if key in error}))
        for frame in error.get('frames', [])[-16:] if isinstance(error.get('frames'), list) else []:
            if not isinstance(frame, dict) or type(frame.get('line')) is not int:
                continue
            file, function = frame.get('file', ''), frame.get('function', '')
            if not (isinstance(file, str) and file.startswith(('backend/', 'scripts/')) and
                    re.fullmatch(r'[A-Za-z_./-]+\.py', file) and '..' not in file):
                file, function = 'external', 'external'
            if not isinstance(function, str) or not re.fullmatch(r'[A-Za-z_<>]{1,80}', function):
                function = 'function'
            entry['frames'].append(dict(file=file, function=function, line=max(0, min(frame['line'], 1000000))))
        exceptions.append(entry)
    if exceptions:
        result['exceptions'] = exceptions
    identity = record.get('record_id')
    result['record_id'] = identity if isinstance(identity, str) and re.fullmatch(r'l_[0-9a-f]{32}', identity) else 'l_' + hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:32]
    # Keep legacy identities stable and ignore any untrusted persisted explanation.
    result['description'] = describe(result['event'], result['context'])
    return result


def collect_diagnostics(root, destination):
    """Create a new ZIP of safe JSONL only; no API/model imports or raw file copying."""
    root, destination = Path(root), Path(destination)
    counts = dict(files=0, events=0, skipped_lines=0, skipped_files=0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        if root.exists():
            if root.is_symlink() or getattr(root.stat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Unsafe diagnostic root')
            for path in sorted(root.iterdir()):
                try:
                    if not FILE_PATTERN.fullmatch(path.name) or not _regular(path):
                        continue
                    info = path.stat()
                except OSError:
                    counts['skipped_files'] += 1
                    continue
                if info.st_size > MAX_BYTES + 65536 or info.st_mtime < time.time() - RETENTION_SECONDS:
                    counts['skipped_files'] += 1
                    continue
                records = []
                try:
                    with path.open('r', encoding='utf-8') as stream:
                        for line in stream:
                            try:
                                value = _export_record(json.loads(line)) if len(line) <= 65536 else None
                            except (ValueError, TypeError):
                                value = None
                            if value is None:
                                counts['skipped_lines'] += 1
                            else:
                                records.append(json.dumps(value, ensure_ascii=True))
                    archive.writestr(f'logs/{path.name}', '\n'.join(records) + ('\n' if records else ''))
                    counts['files'] += 1
                    counts['events'] += len(records)
                except (OSError, UnicodeError):
                    counts['skipped_files'] += 1
            from .diagnostic_archive import archive_content, owned_archives, ARCHIVE_RETENTION, decoded
            for path in owned_archives(root):
                try:
                    content, metadata = archive_content(path)
                    if time.time() - metadata['created_at'] > ARCHIVE_RETENTION:
                        continue
                    values = list(decoded(content))
                    counts['skipped_lines'] += sum(value is None for value in values)
                    safe = [json.dumps(value, ensure_ascii=True) for value in values if value is not None]
                    archive.writestr('archives/' + path.stem + '.jsonl', '\n'.join(safe) + ('\n' if safe else ''))
                    counts['events'] += len(safe)
                    counts['files'] += 1
                except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                    counts['skipped_files'] += 1
        manifest = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
                        python_version=platform.python_version(), app_version=APP_VERSION, **counts,
                        scope='Allowlisted technical events only; no materials, raw stderr, settings or credentials')
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    return manifest
