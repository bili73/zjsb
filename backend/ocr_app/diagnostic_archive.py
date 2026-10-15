"""Owned diagnostic snapshots, independent of business storage and model imports."""
from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
import zipfile
import zlib

ARCHIVE_RETENTION = 30 * 86400
RAW_BUDGET = 512 * 1024 * 1024
ARCHIVE_BUDGET = 1024 * 1024 * 1024
ARCHIVE_PATTERN = re.compile(r'^snapshot-[0-9a-f]{64}\.zip$')
FAILURE_PATTERN = re.compile(r'^failure-[0-9a-f]{32}\.json$')
_thread_lock = threading.RLock()
FILE_ERRORS = (OSError, ValueError, OverflowError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error)


@dataclass
class ReadIssues:
    skipped_files: int = 0
    skipped_records: int = 0

    @property
    def incomplete(self):
        return bool(self.skipped_files or self.skipped_records)

    def metadata(self):
        return dict(incomplete=self.incomplete, skipped_files=self.skipped_files,
                    skipped_records=self.skipped_records)


def file_signature(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass(frozen=True)
class ArchiveMetadata:
    created_at: float
    first: str | None
    last: str | None

    def intersects(self, since, until):
        return self.first is not None and not ((since and self.last < since) or (until and self.first >= until))


class ArchiveIndex:
    """Bounded metadata only; changed files, record emission and deletion still need validation."""
    def __init__(self, capacity=2048):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, path, signature):
        with self.lock:
            entry = self.entries.pop(path, None)
            if entry and entry[0] == signature:
                self.entries[path] = entry
                return entry[1]
        return None

    def put(self, path, signature, metadata):
        with self.lock:
            self.entries.pop(path, None)
            self.entries[path] = (signature, metadata)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)


def archive_metadata(content, manifest):
    first = last = None
    for row in decoded(content):
        if row is None:
            raise ValueError('Incomplete diagnostic archive retained')
        stamp = row['timestamp']
        first = min(first, stamp) if first else stamp
        last = max(last, stamp) if last else stamp
    return ArchiveMetadata(manifest['created_at'], first, last)


def safe_directory(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or getattr(root.stat(), 'st_file_attributes', 0) & 0x400:
        raise OSError('Unsafe diagnostic directory')
    return root


@contextmanager
def locked(root):
    """All writers/maintenance share a bounded OS lock, released on process exit."""
    from .diagnostics import _regular
    with _thread_lock:
        root = safe_directory(root)
        path = root / '.diagnostic.lock'
        if path.exists() and not _regular(path):
            raise OSError('Unsafe diagnostic lock')
        with path.open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            deadline = time.monotonic() + 3
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Diagnostic lock unavailable')
                    time.sleep(.02)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    from .diagnostics import _regular
    if path.exists() and not _regular(path):
        raise OSError('Unsafe diagnostic state')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(json.dumps(value, ensure_ascii=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def owned_raw(root):
    from .diagnostics import FILE_PATTERN, _regular
    return [p for p in Path(root).iterdir() if FILE_PATTERN.fullmatch(p.name) and _regular(p)]


def owned_archives(root):
    from .diagnostics import _regular
    directory = Path(root) / 'archives'
    if not directory.exists():
        return []
    safe_directory(directory)
    return [p for p in directory.iterdir() if ARCHIVE_PATTERN.fullmatch(p.name) and _regular(p)]


def background_files(paths, stop=None):
    """Give live writers a turn between segments (OS lock waiters poll every 20 ms)."""
    began = time.monotonic()
    for path in paths:
        if stop and stop.is_set():
            return
        yield path
        if time.monotonic() - began >= .05:
            if stop:
                stop.wait(.025)
            else:
                time.sleep(.025)
            began = time.monotonic()


def decoded(data):
    from .diagnostics import _export_record
    for line in data.splitlines():
        try:
            value = _export_record(json.loads(line)) if len(line) <= 65536 else None
        except (ValueError, TypeError, UnicodeError):
            value = None
        yield value


def archive_content(path):
    """Validate bounded ZIP entries before decoding; never trust an archive filename."""
    from .diagnostics import MAX_BYTES
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != 2 or {e.filename for e in entries} != {'events.jsonl', 'manifest.json'}:
            raise ValueError('Invalid diagnostic archive')
        if archive.getinfo('events.jsonl').file_size > MAX_BYTES * 2 + 65536 or archive.getinfo('manifest.json').file_size > 4096:
            raise ValueError('Oversized diagnostic archive')
        manifest = json.loads(archive.read('manifest.json'))
        content = archive.read('events.jsonl')
        if (not isinstance(manifest, dict) or manifest.get('owner') != 'ocr-diagnostic-snapshot-v1'
                or manifest.get('content_sha256') != hashlib.sha256(content).hexdigest()
                or type(manifest.get('created_at')) not in (int, float) or not math.isfinite(manifest['created_at'])):
            raise ValueError('Diagnostic archive checksum mismatch')
        return content, manifest


def archive_file(root, path):
    """Called under root lock. A failure must leave the raw file untouched."""
    from .diagnostics import MAX_BYTES, _regular
    if not _regular(path) or path.stat().st_size > MAX_BYTES + 65536:
        raise ValueError('Unsafe diagnostic segment')
    raw = path.read_bytes()
    rows = list(decoded(raw))
    if any(row is None for row in rows):
        raise ValueError('Incomplete diagnostic segment retained')
    content = ''.join(json.dumps(row, ensure_ascii=True) + '\n' for row in rows).encode()
    sha = hashlib.sha256(content).hexdigest()
    directory = safe_directory(Path(root) / 'archives')
    destination = directory / ('snapshot-' + sha + '.zip')
    if destination.exists():
        if not _regular(destination) or archive_content(destination)[0] != content:
            raise ValueError('Existing diagnostic backup is invalid')
        return
    manifest = dict(owner='ocr-diagnostic-snapshot-v1', created_at=time.time(),
                    content_sha256=sha, source_sha256=hashlib.sha256(raw).hexdigest(), records=len(rows))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('events.jsonl', content)
        archive.writestr('manifest.json', json.dumps(manifest))
    data = buffer.getvalue()
    if sum(p.stat().st_size for p in owned_archives(root)) + len(data) > ARCHIVE_BUDGET:
        raise OSError('Diagnostic archive capacity reached')
    temporary = destination.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if archive_content(temporary)[0] != content:
            raise ValueError('Diagnostic archive verification failed')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def maintenance(root, *, daily=False, stop=None, index=None):
    """Bound lock duration to one segment; background work never runs in the OCR watchdog."""
    from .diagnostics import RETENTION_SECONDS
    now = time.time()
    failed = False
    with locked(root):
        backups = owned_archives(root)
    for path in background_files(backups, stop):
        try:
            with locked(root):
                if not path.exists():
                    continue
                # Corrupt/unrecognized archives are retained for investigation, not removed.
                signature = file_signature(path)
                metadata = index.get(path, signature) if index is not None else None
                cached = metadata is not None
                if metadata is None:
                    metadata = archive_metadata(*archive_content(path))
                    if index is not None:
                        index.put(path, signature, metadata)
                if now - metadata.created_at > ARCHIVE_RETENTION:
                    if cached:
                        metadata = archive_metadata(*archive_content(path))
                    if now - metadata.created_at <= ARCHIVE_RETENTION:
                        continue
                    path.unlink()
        except FILE_ERRORS:
            failed = True
    with locked(root):
        files = sorted(owned_raw(root), key=lambda p: p.stat().st_mtime)
        raw_bytes = sum(p.stat().st_size for p in files)
    for path in background_files(files, stop):
        try:
            with locked(root):
                if not path.exists():
                    continue
                info = path.stat()
                # Recently touched files may still be active. A snapshot is safe, but don't reclaim them.
                remove = now - info.st_mtime > RETENTION_SECONDS or (raw_bytes > RAW_BUDGET and now - info.st_mtime > 3600)
                if daily or remove:
                    archive_file(root, path)
                if remove:
                    path.unlink()
                    raw_bytes -= info.st_size
        except FILE_ERRORS:
            failed = True
    if stop and stop.is_set():
        return False
    if raw_bytes > RAW_BUDGET:
        raise OSError('Active diagnostic log capacity reached')
    if failed:
        raise OSError('Some diagnostic files could not be maintained')
    return True


def iter_records(root, *, archives=True, since=None, until=None, stop=None, issues=None, index=None):
    """Read immutable snapshots one at a time and deduplicate daily/live overlap."""
    from .diagnostics import MAX_BYTES
    seen = set()
    issues = issues if issues is not None else ReadIssues()
    with locked(root):
        paths = owned_raw(root)
        backups = owned_archives(root) if archives else []
    for path in background_files(paths + backups, stop):
        manifest = None
        try:
            with locked(root):
                if not path.exists():
                    continue
                if ARCHIVE_PATTERN.fullmatch(path.name):
                    signature = file_signature(path)
                    metadata = index.get(path, signature) if index is not None else None
                    if metadata is not None and not metadata.intersects(since, until):
                        continue
                    content, manifest = archive_content(path)
                else:
                    if path.stat().st_size > MAX_BYTES + 65536:
                        raise ValueError('Oversized diagnostic segment')
                    content = path.read_bytes()
        except FILE_ERRORS:
            issues.skipped_files += 1
            continue
        skipped_before = issues.skipped_records
        first = last = None
        for row in decoded(content):
            if stop and stop.is_set():
                return
            if row is None:
                issues.skipped_records += 1
                continue
            stamp = row['timestamp']
            first = min(first, stamp) if first else stamp
            last = max(last, stamp) if last else stamp
            if (since and row['timestamp'] < since) or (until and row['timestamp'] >= until):
                continue
            identity = row['record_id']
            if identity not in seen:
                seen.add(identity)
                yield row
        if manifest is not None and index is not None and issues.skipped_records == skipped_before:
            index.put(path, signature, ArchiveMetadata(manifest['created_at'], first, last))
