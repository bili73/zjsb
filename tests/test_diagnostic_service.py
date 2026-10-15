"""Failure injection for severity, exact backups and protected diagnostics; no real models."""
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

import test_batch_ownership as ownership
from ocr_app import diagnostics as d
from ocr_app import diagnostic_archive as a
from ocr_app.diagnostic_service import DiagnosticService, window
from ocr_app.diagnostic_messages import EVENT_DESCRIPTIONS, ERROR_DESCRIPTIONS


class ErrorOnlyTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ))
        os.environ.pop('OCR_LOG_LEVEL', None)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_default_and_invalid_level_only_capture_errors_and_critical(self):
        for configured in (None, 'invalid-level'):
            if configured:
                os.environ['OCR_LOG_LEVEL'] = configured
            logger = d.init_diagnostics(self.root / str(configured), 'api')
            logger.event('request_completed')
            logger.event('stderr_drained')
            logger.exception('request_failed', ValueError('SECRET'), http_status=422)
            self.assertFalse(logger.path.exists())
            logger.event('request_timeout', error_code='EXTRACT_TIMEOUT', operation='recognize')
            logger.exception('storage_failed', OSError('SECRET'))
            rows = [json.loads(line) for line in logger.path.read_text().splitlines()]
            self.assertEqual([r['level'] for r in rows], ['ERROR', 'CRITICAL'])
            self.assertIn('识别', rows[0]['description'])
            self.assertIn('存储', rows[1]['description'])
            self.assertNotIn('SECRET', logger.path.read_text())

    def test_empty_error_history_is_healthy_and_startup_probes_writes(self):
        logger = d.init_diagnostics(self.root, 'api')
        service = DiagnosticService(logger)
        service.tick()
        self.assertEqual(service.query()['items'], [])
        self.assertTrue(service.status()['recording_ok'])
        self.assertTrue(service.status()['backup_ok'])
        self.assertTrue(service.status()['scan_ok'])
        with patch.object(d, 'TemporaryFile', side_effect=PermissionError('SECRET')):
            with patch('sys.stderr', io.StringIO()):
                failed = d.init_diagnostics(self.root / 'unwritable', 'api')
        self.assertFalse(failed.available)

    def test_chinese_catalogue_and_legacy_identity_safe_export(self):
        self.assertTrue(d.EVENTS <= EVENT_DESCRIPTIONS.keys())
        self.assertTrue(d.ERROR_CODES <= ERROR_DESCRIPTIONS.keys())
        for text in [*EVENT_DESCRIPTIONS.values(), *ERROR_DESCRIPTIONS.values()]:
            self.assertRegex(text, '[\u4e00-\u9fff]')
        logger = d.init_diagnostics(self.root, 'api')
        logger.exception('request_failed', RuntimeError('SECRET'), error_code='INTERNAL_ERROR')
        row = json.loads(logger.path.read_text())
        row.pop('record_id'); row['description'] = 'SECRET'
        safe = d._export_record(row)
        identity_fields = {k: v for k, v in safe.items() if k not in {'record_id', 'description'}}
        legacy_id = 'l_' + hashlib.sha256(json.dumps(identity_fields, sort_keys=True).encode()).hexdigest()[:32]
        self.assertEqual(safe['record_id'], legacy_id)
        self.assertEqual(d._export_record(safe), safe)
        logger.path.write_text(json.dumps(row) + '\n')
        service = DiagnosticService(logger)
        service.tick()
        self.assertEqual(len(service.query()['items']), 1)
        for data in [service.bundle()[0], None]:
            if data is None:
                path = self.root / 'offline.zip'
                d.collect_diagnostics(self.root, path)
                data = path.read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                contents = '\n'.join(archive.read(name).decode() for name in archive.namelist())
                self.assertNotIn('SECRET', contents)
                records = [json.loads(line) for name in archive.namelist() if name.endswith('.jsonl')
                           for line in archive.read(name).decode().splitlines()]
                self.assertTrue(records)
                self.assertTrue(all('失败' in record['description'] for record in records))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'OCR_LOG_LEVEL': 'INFO'}))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.logger = d.init_diagnostics(self.root, 'api')
        self.service = DiagnosticService(self.logger)

    def test_severity_legacy_identity_and_private_values(self):
        for status, expected in [(409, 'WARNING'), (422, 'WARNING'), (500, 'ERROR')]:
            self.logger.exception('request_failed', RuntimeError('SECRET'), http_status=status, raw_text='SECRET')
            row = json.loads(self.logger.path.read_text().splitlines()[-1])
            self.assertEqual(row['level'], expected)
        self.logger.event('request_timeout', task_id=str(uuid.uuid4()))
        self.logger.exception('storage_failed', OSError('SECRET'))
        self.logger.event('stderr_drained', stderr_lines=2)
        text = self.logger.path.read_text()
        self.assertNotIn('SECRET', text)
        self.assertNotIn('stderr_drained', text)
        rows = list(a.iter_records(self.root))
        self.assertEqual(rows[-1]['level'], 'CRITICAL')
        self.assertTrue(all(row['app_version'] == '1.26.0' for row in rows))
        legacy = dict(rows[0]); legacy.pop('record_id'); legacy.pop('level'); legacy.pop('app_version')
        safe = d._export_record(legacy)
        self.assertEqual(d._export_record(safe), safe)
        self.assertEqual(safe['app_version'], 'unknown')
        with patch.dict(os.environ, {'OCR_LOG_LEVEL': 'DEBUG'}):
            debug = d.init_diagnostics(self.root, 'client')
            debug.event('stderr_drained', stderr_lines=2)
            self.assertEqual(json.loads(debug.path.read_text().splitlines()[-1])['level'], 'DEBUG')

    def test_daily_backup_deduplicates_and_restart_keeps_state(self):
        self.service.tick()
        backups = a.owned_archives(self.root)
        self.assertEqual(len(backups), 1)
        first = self.service.status()['last_backup_at']
        self.assertTrue(self.service.status()['backup_ok'])
        self.service.tick()
        self.assertEqual(a.owned_archives(self.root), backups)
        restarted = DiagnosticService(self.logger)
        restarted.tick()
        self.assertEqual(restarted.status()['last_backup_at'], first)
        self.assertEqual(len(list(a.iter_records(self.root))), 1)

    def test_history_maintenance_yields_to_live_log_writer(self):
        for _ in range(40):
            self.logger.event('request_completed')
            with a.locked(self.root):
                a.archive_file(self.root, self.logger.path)
        entered, finished = threading.Event(), threading.Event()
        reads = []
        original = a.archive_content
        def slow_archive(path):
            entered.set()
            time.sleep(.03)
            reads.append(path)
            return original(path)
        def maintain():
            try:
                a.maintenance(self.root)
            finally:
                finished.set()
        with patch.object(a, 'archive_content', side_effect=slow_archive):
            worker = threading.Thread(target=maintain)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.logger.event('request_timeout')
                self.assertLess(len(reads), 40, 'A live writer waited for every historical archive')
                self.assertFalse(finished.is_set(), 'A live writer waited for the whole archive history')
                self.assertTrue(self.logger.available)
            finally:
                worker.join(5)
        self.assertTrue(finished.is_set())

    def test_rotate_archives_every_discarded_record(self):
        expected = set()
        with patch.object(d, 'MAX_BYTES', 900):
            for _ in range(20):
                row = self.logger._record('request_completed', {})
                expected.add(row['record_id'])
                self.logger._write(row)
            self.assertTrue(self.logger.available)
            ids = {row['record_id'] for row in a.iter_records(self.root)}
        self.assertTrue(expected <= ids)
        self.assertGreater(len(a.owned_archives(self.root)), 0)

    def test_archive_failure_preserves_expired_source_and_is_visible(self):
        old = time.time() - 8 * 86400
        os.utime(self.logger.path, (old, old))
        original = self.logger.path.read_bytes()
        with patch.object(a, 'ARCHIVE_BUDGET', 1):
            self.service.tick()
        self.assertFalse(self.service.status()['backup_ok'])
        self.assertEqual(self.logger.path.read_bytes(), original)
        self.service.tick()
        self.assertTrue(self.service.status()['backup_ok'])
        self.assertFalse(self.logger.path.exists())
        self.assertEqual(len(list(a.iter_records(self.root))), 1)

    def test_partial_record_or_corrupt_zip_never_authorizes_delete(self):
        with self.logger.path.open('ab') as stream:
            stream.write(b'{"unfinished":')
        old = time.time() - 8 * 86400
        os.utime(self.logger.path, (old, old))
        self.service.tick()
        self.assertTrue(self.logger.path.exists())
        self.assertFalse(self.service.status()['backup_ok'])
        self.assertFalse(self.service.status()['scan_ok'])

    def test_expired_archive_only_and_unrelated_files_untouched(self):
        self.service.tick()
        target = a.owned_archives(self.root)[0]
        unrelated = self.root / 'materials'
        unrelated.mkdir()
        material = unrelated / 'record.jsonl'
        material.write_text('KEEP')
        with patch.object(a, 'ARCHIVE_RETENTION', -1):
            a.maintenance(self.root)
        self.assertFalse(target.exists())
        self.assertEqual(material.read_text(), 'KEEP')

    def test_failed_rotation_preserves_last_segment_and_recovers(self):
        with patch.object(d, 'MAX_BYTES', 900):
            for _ in range(12):
                self.logger.event('request_completed')
            last = Path(str(self.logger.path) + '.4')
            previous = last.read_bytes()
            with patch.object(a, 'archive_file', side_effect=OSError('private path')):
                with patch('sys.stderr', io.StringIO()):
                    for _ in range(3):
                        self.logger.event('request_completed')
            self.assertFalse(self.logger.available)
            self.assertEqual(previous, last.read_bytes())
            self.assertFalse(self.service.status()['recording_ok'])
            self.logger.retry_at = 0
            self.logger.event('request_completed')
            self.assertTrue(self.logger.available)
            self.assertFalse(list(self.root.glob('failure-*.json')))

    def test_query_paging_filters_and_safe_bundle(self):
        task = str(uuid.uuid4())
        for _ in range(4):
            self.logger.event('request_timeout', task_id=task)
        self.service.tick()
        first = self.service.query(level='ERROR', task_id=task, limit=2)
        second = self.service.query(level='ERROR', task_id=task, limit=2, cursor=first['next_cursor'])
        self.assertEqual(len(first['items'] + second['items']), 4)
        self.assertIsNone(second['next_cursor'])
        self.assertFalse({r['record_id'] for r in first['items']} & {r['record_id'] for r in second['items']})
        data, truncated = self.service.bundle(task_id=task)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['records'], 4)
            self.assertIsNone(archive.testzip())
        self.assertFalse(truncated)
        start, end = window('2026-10-15', '2026-10-15')
        self.assertEqual(start, '2026-10-14T16:00:00+00:00')
        self.assertEqual(end, '2026-10-15T16:00:00+00:00')


class DiagnosticAPITests(unittest.TestCase):
    account = ownership.BatchOwnershipTests.account
    password = ownership.BatchOwnershipTests.password

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'OCR_LOG_LEVEL': 'INFO'}))
        ownership.BatchOwnershipTests.setUp(self)
        self.logger = d.init_diagnostics(self.root / 'diagnostics', 'api')
        self.service = DiagnosticService(self.logger)
        self.client.app.state.diagnostics = self.service

    def test_only_admin_can_read_or_download_and_public_health_stays_minimal(self):
        for role in ['operator', 'viewer', 'admin']:
            _, headers, _ = self.account(role, role)
            for endpoint in ['status', 'events', 'bundle']:
                path = '/api/v1/admin/diagnostics/' + endpoint
                self.assertEqual(self.client.get(path).status_code, 401)
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 200 if role == 'admin' else 403, response.text[:200])
        self.assertEqual(set(self.client.get('/health').json()), {'status'})

    def test_revocation_after_slow_query_or_bundle_denies_content(self):
        for operation, endpoint in [('query', 'events'), ('bundle', 'bundle')]:
            _, headers, token = self.account(operation, 'admin')
            original = getattr(self.service, operation)
            def revoke(**kwargs):
                value = original(**kwargs)
                self.business.accounts.logout(token)
                return value
            with patch.object(self.service, operation, side_effect=revoke):
                response = self.client.get('/api/v1/admin/diagnostics/' + endpoint, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('initialized', response.text)

    def test_frontend_report_is_safe_attributed_rate_limited_and_requires_csrf(self):
        actor, headers, _ = self.account('reporter', 'viewer')
        body = dict(origin='vue', operation='interface', code='CLIENT_ERROR', client_error_id=str(uuid.uuid4()), line=42, column=3)
        url = '/api/v1/diagnostics/frontend'
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        missing = {key: value for key, value in headers.items() if key != 'X-CSRF-Token'}
        self.assertEqual(self.client.post(url, json=body, headers=missing).status_code, 403)
        self.assertEqual(self.client.post(url, json=dict(body, raw_text='SECRET'), headers=headers).status_code, 422)
        response = self.client.post(url, json=body, headers=headers)
        self.assertEqual(response.status_code, 202)
        row = list(a.iter_records(self.logger.root))[-1]
        self.assertEqual(row['context']['actor_id'], actor['user_id'])
        self.assertEqual(len(self.service.query(error_id=body['client_error_id'])['items']), 1)
        self.assertNotIn('SECRET', self.logger.path.read_text())
        for _ in range(8):
            self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 202)
        self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 429)

    def test_invalid_date_and_cursor_are_not_server_errors(self):
        _, headers, _ = self.account('reader', 'admin')
        for query in ['cursor=invalid', 'date_from=2026-01-01&date_to=2026-10-15', 'level=secret', 'task_id=../secret']:
            response = self.client.get('/api/v1/admin/diagnostics/events?' + query, headers=headers)
            self.assertEqual(response.status_code, 422, response.text)
