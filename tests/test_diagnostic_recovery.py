"""Synthetic diagnostic lock contention, partial recovery and bounded index regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
import zipfile

from fastapi.testclient import TestClient
import test_business_api as base
import test_diagnostic_service as existing
from ocr_app.api import create_app
from ocr_app import diagnostic_archive as a
from ocr_app import diagnostics as d
from ocr_app.diagnostic_service import DiagnosticService
from ocr_app.task_store import TaskError


def health_while_log_locked(test, client, logger, request):
    attempted = threading.Event()
    original = logger._write
    def write(row):
        attempted.set()
        return original(row)
    with patch.object(logger, '_write', side_effect=write), ThreadPoolExecutor(max_workers=2) as pool:
        with a.locked(logger.root):
            pending = pool.submit(request)
            test.assertTrue(attempted.wait(2), 'Request did not attempt diagnostic logging')
            health = pool.submit(client.get, '/health')
            # The held lock is released only AFTER health completes: latency is not the assertion.
            test.assertEqual(health.result(timeout=2).status_code, 200)
            test.assertFalse(pending.done())
        return pending.result(timeout=3)


class ReportConcurrencyTests(unittest.TestCase):
    setUp = existing.DiagnosticAPITests.setUp
    account = existing.DiagnosticAPITests.account
    password = existing.DiagnosticAPITests.password

    def test_frontend_report_waits_off_loop_and_remains_attributed(self):
        _, headers, _ = self.account('reporter', 'viewer')
        body = dict(origin='vue', operation='interface', code='CLIENT_ERROR', client_error_id=str(uuid.uuid4()))
        response = health_while_log_locked(self, self.client, self.logger,
            lambda: self.client.post('/api/v1/diagnostics/frontend', headers=headers, json=body))
        self.assertEqual(response.status_code, 202)

    def test_partial_api_response_and_bundle_expose_incomplete_but_not_truncated(self):
        _, headers, _ = self.account('reader', 'admin')
        with self.logger.path.open('ab') as stream:
            stream.write(b'PRIVATE broken line\n')
        response = self.client.get('/api/v1/admin/diagnostics/events', headers=headers)
        self.assertEqual(response.status_code, 200)
        page = response.json()
        self.assertTrue(page['incomplete'])
        self.assertEqual(page['skipped_records'], 1)
        self.assertTrue(page['items'])
        self.assertNotIn('PRIVATE', response.text)
        response = self.client.get('/api/v1/admin/diagnostics/bundle', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Diagnostics-Incomplete'], 'true')
        self.assertEqual(response.headers['X-Diagnostics-Truncated'], 'false')
        with patch.object(a, 'owned_raw', side_effect=PermissionError('PRIVATE directory')):
            response = self.client.get('/api/v1/admin/diagnostics/events', headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.text)


class ErrorResponseConcurrencyTests(unittest.TestCase):
    def test_exception_handlers_and_success_middleware_wait_off_loop(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OCR_LOG_LEVEL': 'INFO'}):
            root = Path(folder)
            logger = d.init_diagnostics(root / 'diagnostics', 'api')
            app = create_app(base.FakeRuntime(), root / 'static', root / 'storage', logger=logger)
            @app.post('/synthetic/{kind}')
            async def synthetic(kind: str):
                if kind == 'task':
                    raise TaskError('INTERNAL_ERROR', 'Synthetic failure', 500)
                if kind == 'unexpected':
                    raise RuntimeError('PRIVATE')
                return {'ok': True}
            with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 123), raise_server_exceptions=False) as client:
                app.state.diagnostics.close()
                for kind, expected in [('task', 500), ('unexpected', 500), ('success', 200)]:
                    response = health_while_log_locked(self, client, logger,
                        lambda: client.post('/synthetic/' + kind))
                    self.assertEqual(response.status_code, expected)
                    self.assertNotIn('PRIVATE', response.text)


class PartialRecoveryTests(unittest.TestCase):
    setUp = existing.ArchiveTests.setUp

    def test_damaged_segments_preserve_evidence_and_allow_other_backups_and_reads(self):
        damaged = self.logger.path
        damaged.write_bytes(damaged.read_bytes() + b'{"unfinished":')
        original = damaged.read_bytes()
        broken_zip = a.safe_directory(self.root / 'archives') / ('snapshot-' + 'f' * 64 + '.zip')
        broken_zip.write_bytes(b'broken archive PRIVATE')
        good = d.init_diagnostics(self.root, 'client')
        good.event('request_timeout')
        expected = {r['record_id'] for r in a.decoded(original) if r}
        expected.update(r['record_id'] for r in a.decoded(good.path.read_bytes()) if r)
        for service in (self.service, DiagnosticService(self.logger)):
            service.tick()
            self.assertFalse(service.status()['backup_ok'])
            self.assertFalse(service.status()['scan_ok'])
            self.assertEqual(damaged.read_bytes(), original)
            self.assertEqual(broken_zip.read_bytes(), b'broken archive PRIVATE')
            self.assertGreater(len(a.owned_archives(self.root)), 1)
            page = service.query()
            self.assertEqual({r['record_id'] for r in page['items']}, expected)
            self.assertEqual((page['incomplete'], page['skipped_files'], page['skipped_records']), (True, 1, 1))
            data, metadata = service.bundle()
            self.assertTrue(metadata['incomplete'])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual((manifest['incomplete'], manifest['skipped_files'], manifest['skipped_records']), (True, 1, 1))
                self.assertFalse(manifest['truncated'])
                rows = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
                self.assertEqual({r['record_id'] for r in rows}, expected)
                self.assertNotIn(b'PRIVATE', archive.read('events.jsonl'))

    def test_failed_checkpoint_does_not_advance_backup_day(self):
        with patch('ocr_app.diagnostic_service.atomic_json', side_effect=OSError('PRIVATE')):
            self.service.tick()
        self.assertFalse(self.service.status()['backup_ok'])
        self.assertIsNone(self.service.last_day)
        self.assertIsNone(self.service.status()['last_backup_at'])
        self.service.tick()
        self.assertTrue(self.service.status()['backup_ok'])
        self.assertIsNotNone(self.service.last_day)

    def test_damaged_expired_source_does_not_block_deletion_of_other_verified_sources(self):
        import time
        bad = self.logger.path
        original = bad.read_bytes() + b'{"unfinished":'
        bad.write_bytes(original)
        healthy = d.init_diagnostics(self.root, 'client')
        old = time.time() - 8 * 86400
        for path in (bad, healthy.path):
            os.utime(path, (old, old))
        self.service.tick()
        self.assertEqual(bad.read_bytes(), original)
        self.assertFalse(healthy.path.exists())
        self.assertFalse(self.service.status()['backup_ok'])
        self.assertEqual(len(self.service.query()['items']), 2)

    def test_checksum_valid_but_invalid_record_archive_is_retained_and_reported(self):
        import hashlib
        valid = self.logger.path.read_bytes()
        content = valid + b'PRIVATE invalid record\n'
        path = a.safe_directory(self.root / 'archives') / ('snapshot-' + 'e' * 64 + '.zip')
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('events.jsonl', content)
            archive.writestr('manifest.json', json.dumps(dict(owner='ocr-diagnostic-snapshot-v1',
                created_at=0, content_sha256=hashlib.sha256(content).hexdigest())))
        original = path.read_bytes()
        self.service.tick()
        self.assertEqual(path.read_bytes(), original)
        page = self.service.query()
        self.assertTrue(page['incomplete'])
        self.assertEqual(page['skipped_records'], 1)
        self.assertEqual(len(page['items']), 1)


class ArchiveIndexTests(unittest.TestCase):
    setUp = existing.ArchiveTests.setUp

    def old_archive(self):
        row = self.logger._record('request_timeout', {})
        row['timestamp'] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.logger.path.write_text(json.dumps(row) + '\n')
        with a.locked(self.root):
            a.archive_file(self.root, self.logger.path)
            self.logger.path.unlink()
        return a.owned_archives(self.root)[0], row

    def test_repeated_recent_scan_skips_old_archives_but_all_history_stays_queryable(self):
        path, old = self.old_archive()
        self.logger.event('request_timeout')
        self.service.tick()
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        with patch.object(a, 'archive_content', wraps=a.archive_content) as reads:
            self.service.tick()
            page = self.service.query(date_from=today, date_to=today)
            self.assertNotIn(path, [call.args[0] for call in reads.call_args_list])
        self.assertEqual(len(page['items']), 1)
        self.assertFalse(page['incomplete'])
        self.assertEqual(len(self.service.query()['items']), 2)
        self.assertIn(old['record_id'], {r['record_id'] for r in DiagnosticService(self.logger).query()['items']})

    def test_signature_change_invalidates_index_and_expiry_revalidates_content(self):
        path, _ = self.old_archive()
        self.service.tick()
        content, manifest = a.archive_content(path)
        row = json.loads(content)
        row['timestamp'] = datetime.now(timezone.utc).isoformat()
        content = (json.dumps(row) + '\n').encode()
        import hashlib
        manifest['content_sha256'] = hashlib.sha256(content).hexdigest()
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('events.jsonl', content)
            archive.writestr('manifest.json', json.dumps(manifest))
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        self.assertEqual(len(self.service.query(date_from=today, date_to=today)['items']), 1)
        # A warm index must never authorize deletion without reading the actual archive again.
        with patch.object(a, 'ARCHIVE_RETENTION', -1), patch.object(a, 'archive_content', side_effect=ValueError('synthetic damage')):
            self.service.tick()
        self.assertFalse(self.service.status()['backup_ok'])
        self.assertTrue(path.exists())
        a.maintenance(self.root, index=self.service.archive_index)
        path.write_bytes(b'corrupt replacement')
        page = self.service.query(date_from=today, date_to=today)
        self.assertTrue(page['incomplete'])
        self.assertEqual(page['skipped_files'], 1)

    def test_index_eviction_and_deleted_files_do_not_return_phantom_records(self):
        path, _ = self.old_archive()
        self.service.archive_index = a.ArchiveIndex(capacity=1)
        self.service.tick()
        self.logger.event('request_timeout')
        with a.locked(self.root):
            a.archive_file(self.root, self.logger.path)
            self.logger.path.unlink()
        self.assertEqual(len(self.service.query()['items']), 2)
        self.assertEqual(len(self.service.archive_index.entries), 1)
        path.unlink()
        self.assertEqual(len(self.service.query()['items']), 1)
