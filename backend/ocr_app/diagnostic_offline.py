"""Read-only serious-event export without locks, state files, keys or business imports."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import stat
import zipfile

from . import diagnostics as d
from .diagnostic_archive import (ARCHIVE_PATTERN, FILE_ERRORS, ReadIssues, archive_content,
                                 decoded, file_signature)
from .diagnostic_service import MAX_DOWNLOAD


def directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise OSError('Unsafe diagnostic directory')


def inventory(root):
    directory(root)
    paths = [p for p in root.iterdir() if d.FILE_PATTERN.fullmatch(p.name)]
    result = {}
    archives = root / 'archives'
    if archives.exists() or archives.is_symlink():
        try:
            directory(archives)
            paths += [p for p in archives.iterdir() if ARCHIVE_PATTERN.fullmatch(p.name)]
        except FILE_ERRORS:
            result[archives] = None
    for path in paths:
        try:
            result[path] = file_signature(path) if d._regular(path) else None
        except FILE_ERRORS:
            result[path] = None
    return result


def collect_source(root, *, budget=MAX_DOWNLOAD):
    root = Path(root)
    issues, payload, seen = ReadIssues(), bytearray(), set()
    now = datetime.now(timezone.utc)
    since, until = (now - timedelta(days=30)).isoformat(), now.isoformat()
    manifest = dict(available=True, truncated=False, records=0, date_from=since, date_to=until,
                    levels=['ERROR', 'CRITICAL'], coverage='matching readable records in the stated window')
    try:
        files = inventory(root)
    except FILE_ERRORS:
        files = {}
        manifest['available'] = False
        issues.interrupted = True
    for path, signature in files.items():
        try:
            if signature is None or not d._regular(path):
                raise OSError('Unsafe diagnostic segment')
            if ARCHIVE_PATTERN.fullmatch(path.name):
                content, _ = archive_content(path)
            else:
                with path.open('rb') as stream:
                    content = stream.read(d.MAX_BYTES + 65537)
                if len(content) > d.MAX_BYTES + 65536:
                    raise ValueError('Oversized diagnostic segment')
            if file_signature(path) != signature or (content and not content.endswith(b'\n')):
                issues.interrupted = True
            for row in decoded(content):
                if row is None:
                    issues.skipped_records += 1
                    continue
                if row['level'] not in {'ERROR', 'CRITICAL'} or not since <= row['timestamp'] < until or row['record_id'] in seen:
                    continue
                line = (json.dumps(row, ensure_ascii=True) + '\n').encode()
                if len(payload) + len(line) > budget:
                    manifest['truncated'] = True
                    break
                payload.extend(line)
                seen.add(row['record_id'])
            if manifest['truncated']:
                break
        except FILE_ERRORS:
            issues.skipped_files += 1
    if manifest['available']:
        try:
            issues.interrupted |= inventory(root) != files
        except FILE_ERRORS:
            issues.interrupted = True
    manifest.update(records=len(seen), **issues.metadata())
    return bytes(payload), manifest


def source_bundle(root):
    payload, manifest = collect_source(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('events.jsonl', payload)
        archive.writestr('manifest.json', json.dumps(manifest))
    return buffer.getvalue()
