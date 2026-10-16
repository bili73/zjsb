"""Small local diagnostic query/maintenance service; never imports model engines."""
import base64
from collections import deque
from datetime import datetime, timedelta, timezone
import heapq
import io
import json
from pathlib import Path
import re
import threading
import time
import zipfile

from . import diagnostics as d
from .diagnostic_archive import (ARCHIVE_BUDGET, FAILURE_PATTERN, RAW_BUDGET, ArchiveIndex, ReadIssues,
                                 atomic_json, iter_records, locked, maintenance,
                                 owned_archives, owned_raw)
from .task_errors import TaskError

SHANGHAI = timezone(timedelta(hours=8))
MAX_DOWNLOAD = 64 * 1024 * 1024


def window(date_from=None, date_to=None):
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(date_from).replace(tzinfo=SHANGHAI) if date_from else now - timedelta(days=30)
    end = datetime.fromisoformat(date_to).replace(tzinfo=SHANGHAI) + timedelta(days=1) if date_to else now + timedelta(seconds=1)
    if start >= end or end - start > timedelta(days=31):
        raise TaskError('INVALID_REQUEST', '日志查询日期范围不能超过31天', 422)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


class DiagnosticService:
    def __init__(self, logger):
        self.logger, self.root = logger, Path(logger.root)
        self.stop_event = threading.Event()
        self.thread = None
        self.query_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.archive_index = ArchiveIndex()
        self.reports = {}
        self.state = dict(last_backup_at=None, backup_ok=None, last_check_at=None, scan_ok=None,
                          raw_bytes=0, archive_bytes=0, error_count_24h=0, latest_error_at=None,
                          latest_error_id=None, recording_ok=logger.available)
        self.last_day = None
        try:
            path = self.root / 'maintenance.json'
            if d._regular(path):
                old = json.loads(path.read_text())
                if isinstance(old, dict) and isinstance(old.get('last_backup_at'), str) and re.fullmatch(r'[0-9T:+.Z-]{20,40}', old['last_backup_at']):
                    self.state['last_backup_at'] = old['last_backup_at']
                    self.last_day = old.get('backup_day')
        except (OSError, ValueError, TypeError):
            pass

    def start(self):
        def run():
            while not self.stop_event.is_set():
                self.tick()
                self.stop_event.wait(30)
        self.thread = threading.Thread(target=run, name='diagnostic-maintenance', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def tick(self):
        now = datetime.now(timezone.utc)
        day = now.astimezone(SHANGHAI).date().isoformat()
        backup = dict(backup_ok=False)
        try:
            if not maintenance(self.root, daily=day != self.last_day, stop=self.stop_event, index=self.archive_index):
                return
            stamp = now.isoformat() if day != self.last_day else self.state['last_backup_at']
            with locked(self.root):
                atomic_json(self.root / 'maintenance.json', dict(backup_day=day, last_backup_at=stamp))
            self.last_day = day
            backup.update(backup_ok=True, last_backup_at=stamp)
        except Exception:
            # Visible status does not depend on being able to write another error record.
            pass
        scan = dict(scan_ok=False, last_check_at=now.isoformat())
        try:
            since = (now - timedelta(days=1)).isoformat()
            issues = ReadIssues()
            count, latest = 0, None
            for row in iter_records(self.root, since=since, stop=self.stop_event, issues=issues, index=self.archive_index):
                if d.LEVELS[row['level']] >= 40:
                    count += 1
                    if latest is None or (row['timestamp'], row['record_id']) > (latest['timestamp'], latest['record_id']):
                        latest = row
            if self.stop_event.is_set():
                return
            with locked(self.root):
                raw_size = sum(p.stat().st_size for p in owned_raw(self.root))
                archive_size = sum(p.stat().st_size for p in owned_archives(self.root))
                failed = False
                for path in self.root.iterdir():
                    if not FAILURE_PATTERN.fullmatch(path.name) or not d._regular(path) or path.stat().st_size > 4096:
                        continue
                    marker = json.loads(path.read_text())
                    # Previous crashed sessions remain evidence, not a false current-write alarm.
                    failed = failed or marker.get('session_id') == self.logger.session_id
            scan.update(scan_ok=not issues.incomplete, raw_bytes=raw_size, archive_bytes=archive_size,
                        recording_ok=self.logger.available and not failed, error_count_24h=count,
                        latest_error_at=latest['timestamp'] if latest else None,
                        latest_error_id=latest['record_id'] if latest else None)
        except Exception:
            scan['recording_ok'] = self.logger.available
        with self.state_lock:
            self.state.update(backup, **scan)

    def status(self):
        with self.state_lock:
            state = dict(self.state)
        state['recording_ok'] = state['recording_ok'] and self.logger.available
        return dict(state, raw_retention_days=7, backup_retention_days=30,
                    raw_limit_bytes=RAW_BUDGET, archive_limit_bytes=ARCHIVE_BUDGET)

    def records(self, *, level=None, date_from=None, date_to=None, error_id=None, task_id=None, issues=None, stop=None):
        if level is not None and level not in {'ERROR', 'CRITICAL'}:
            raise TaskError('INVALID_REQUEST', '仅可查询 ERROR 和 CRITICAL 严重日志', 422)
        start, end = window(date_from, date_to)
        for row in iter_records(self.root, since=start, until=end, issues=issues, index=self.archive_index, stop=stop):
            context = row['context']
            if row['level'] not in {'ERROR', 'CRITICAL'} or (level and row['level'] != level):
                continue
            if error_id and error_id not in {context.get('error_id'), context.get('client_error_id'), context.get('request_id'), row['record_id']}:
                continue
            if task_id and context.get('task_id') != task_id:
                continue
            yield row

    def query(self, *, cursor=None, limit=50, **filters):
        before = None
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
                if not isinstance(value, list) or len(value) != 2 or not re.fullmatch(r'[0-9T:+.Z-]{20,40}', value[0]) or not re.fullmatch(r'l_[0-9a-f]{32}', value[1]):
                    raise ValueError()
                before = tuple(value)
            except (ValueError, TypeError):
                raise TaskError('INVALID_REQUEST', '日志分页参数无效', 422) from None
        if not self.query_lock.acquire(blocking=False):
            raise TaskError('DIAGNOSTICS_BUSY', '日志正在读取，请稍后重试', 409)
        try:
            issues = ReadIssues()
            key = lambda row: (row['timestamp'], row['record_id'])
            rows = heapq.nlargest(limit + 1, (row for row in self.records(issues=issues, **filters) if before is None or key(row) < before), key=key)
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = base64.urlsafe_b64encode(json.dumps(key(rows[-1])).encode()).decode().rstrip('=') if more else None
            if issues.incomplete:
                with self.state_lock:
                    self.state['scan_ok'] = False
            return dict(items=rows, next_cursor=next_cursor, **issues.metadata())
        except TaskError:
            raise
        except Exception:
            with self.state_lock:
                self.state['scan_ok'] = False
            raise TaskError('DIAGNOSTICS_UNAVAILABLE', '日志读取失败，请使用离线收集脚本并检查存储', 503) from None
        finally:
            self.query_lock.release()

    def bundle(self, **filters):
        if not self.query_lock.acquire(blocking=False):
            raise TaskError('DIAGNOSTICS_BUSY', '日志正在读取，请稍后重试', 409)
        try:
            payload, count, truncated = bytearray(), 0, False
            issues = ReadIssues()
            for row in self.records(issues=issues, **filters):
                line = (json.dumps(row, ensure_ascii=True) + '\n').encode()
                if len(payload) + len(line) > MAX_DOWNLOAD:
                    truncated = True
                    break
                payload.extend(line)
                count += 1
            metadata = dict(truncated=truncated, **issues.metadata())
            if issues.incomplete:
                with self.state_lock:
                    self.state['scan_ok'] = False
            manifest = dict(schema_version=2, app_version=d.APP_VERSION, created_at=datetime.now(timezone.utc).isoformat(),
                            records=count, **metadata, status=self.status(), scope='Allowlisted technical events only')
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('events.jsonl', payload)
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True))
            return buffer.getvalue(), metadata
        except TaskError:
            raise
        except Exception:
            raise TaskError('DIAGNOSTICS_UNAVAILABLE', '诊断包生成失败，原日志已保留', 503) from None
        finally:
            self.query_lock.release()

    def admit_report(self, actor):
        with self.rate_lock:
            now = time.monotonic()
            self.reports = {key: entries for key, entries in self.reports.items() if entries and now - entries[-1] < 60}
            entries = self.reports.setdefault(actor, deque())
            while entries and now - entries[0] >= 60:
                entries.popleft()
            if len(entries) >= 10 or len(self.reports) > 1000:
                raise TaskError('DIAGNOSTICS_RATE_LIMITED', '诊断上报频率过高，请稍后重试', 429)
            entries.append(now)
