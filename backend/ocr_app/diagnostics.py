"""Bounded, allowlisted diagnostics. Never serialize material, messages or locals."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import sys
import threading
import time
import traceback
import uuid
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / '.runtime' / 'diagnostics'
MAX_BYTES = 10 * 1024 * 1024
FILE_COUNT = 5
RETENTION_SECONDS = 7 * 86400
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
upload_rejected pipeline_failed watchdog_timeout migration_failed retention_failed'''.split())
ERROR_CODES = set('''RESOURCE_LIMIT MODEL_LOAD_FAILED MODEL_WARMUP_FAILED MODEL_PROCESS_EXITED
SUPERVISION_FAILED MODEL_REQUEST_TIMEOUT INPUT_INVALID INVALID_REQUEST RUNTIME_STARTING
RUNTIME_BUSY CUDA_UNAVAILABLE CONNECTION_FAILED INVALID_HEALTH DIAGNOSTICS_UNAVAILABLE
EXTRACT_TIMEOUT WORKER_INTERRUPTED DECODE_FAILED UNSUPPORTED_DOC_TYPE UNSUPPORTED_FORMAT FILE_TOO_LARGE
INTERNAL_ERROR RESULT_VERSION_CONFLICT INVALID_STATE FORBIDDEN_REVEAL'''.split())
ENUMS = {
    'model': {'glm_ocr', 'paddleocr_vl', 'glm-ocr', 'paddleocr-vl'},
    'phase': {'loading', 'warming', 'ready', 'starting', 'stopping', 'recognize', 'unloaded', 'failed'},
    'operation': {'load', 'recognize', 'statistics', 'shutdown', 'stop_task', 'startup', 'close'},
    'configured_mode': {'dual_resident', 'single_resident'},
    'effective_mode': {'dual_resident', 'single_resident', 'ocr_unavailable'},
    'state': {'starting', 'ready', 'degraded', 'stopping'},
    'termination_reason': {'eos', 'token_limit', 'repetition_stop', 'time_limit'},
    'error_code': ERROR_CODES, 'reason_code': ERROR_CODES,
    'stage': {'BOOTSTRAP', 'QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING', 'PUBLISHING', 'CLEANUP'},
}
IDS = {'task_id', 'run_id', 'page_id', 'region_id', 'request_id', 'process_instance_id'}
NUMBERS = {'pid', 'child_pid', 'exit_code', 'duration_seconds', 'timeout_seconds', 'output_tokens',
           'stderr_characters', 'stderr_lines', 'page', 'region', 'errno', 'winerror', 'http_status',
           'load_seconds', 'warmup_seconds', 'recognition_seconds', 'elapsed_seconds', 'gpu_peak_allocated_gib',
           'gpu_peak_reserved_gib', 'gpu_allocated_gib', 'gpu_reserved_gib', 'rss_gib', 'warmup_tokens',
           'generation_timeout_seconds', 'max_new_tokens', 'queue_wait_seconds'}
EXCEPTION_TYPES = set('''Exception BaseException RuntimeError ValueError TypeError KeyError OSError
PermissionError FileNotFoundError FileExistsError TimeoutError MemoryError ImportError ModuleNotFoundError
BrokenPipeError UnicodeError UnicodeDecodeError JSONDecodeError AssertionError RuntimeFailure JobError TaskError DocumentError
OutOfMemoryError UnidentifiedImageError DecompressionBombError KeyboardInterrupt SystemExit'''.split())
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
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if self.root.is_symlink() or getattr(self.root.stat(), 'st_file_attributes', 0) & 0x400:
                raise OSError('Unsafe diagnostic root')
            # Direct owned files only; never recurse or touch legacy stderr/materials.
            for path in self.root.iterdir():
                try:
                    if FILE_PATTERN.fullmatch(path.name) and _regular(path):
                        if path.stat().st_mtime < time.time() - RETENTION_SECONDS:
                            path.unlink()
                except FileNotFoundError:
                    pass
            self.event('initialized')
        except Exception:
            self.available = False
            _warning()

    def _write(self, record):
        if self.closed or not self.available:
            return
        try:
            encoded = (json.dumps(record, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
            with self.lock:
                if self.path.exists() and self.path.stat().st_size + len(encoded) > MAX_BYTES:
                    for number in range(FILE_COUNT - 1, 0, -1):
                        source = self.path if number == 1 else Path(str(self.path) + f'.{number - 1}')
                        target = Path(str(self.path) + f'.{number}')
                        if source.exists():
                            source.replace(target)
                with self.path.open('ab') as stream:
                    stream.write(encoded)
                    stream.flush()
        except Exception:
            self.available = False
            _warning()

    def _record(self, event, context):
        return dict(owner=OWNER, version=1, timestamp=datetime.now(timezone.utc).isoformat(),
                    component=self.component, session_id=self.session_id, pid=os.getpid(),
                    process_instance_id=opaque_id(self.instance), event=event if isinstance(event, str) and event in EVENTS else 'event',
                    context=safe_context(context))

    def event(self, event, **context):
        self._write(self._record(event, context))

    def exception(self, event, error, **context):
        error_id = 'e_' + uuid.uuid4().hex
        try:
            record = self._record(event, {**context, 'error_id': error_id})
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
    exceptions = []
    for error in record.get('exceptions', [])[:4] if isinstance(record.get('exceptions'), list) else []:
        if not isinstance(error, dict):
            continue
        entry = dict(type=error.get('type') if error.get('type') in EXCEPTION_TYPES else 'Exception', frames=[])
        entry.update(safe_context({key: error.get(key) for key in ('errno', 'winerror')}))
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
        manifest = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
                        python_version=platform.python_version(), **counts,
                        scope='Allowlisted technical events only; no materials, raw stderr, settings or credentials')
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    return manifest
