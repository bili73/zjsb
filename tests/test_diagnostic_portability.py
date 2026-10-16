"""Portable diagnostic helpers do not require application/model dependencies."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

from ocr_app import diagnostics as d
from ocr_app.diagnostic_archive import ReadIssues
from ocr_app.diagnostic_offline import collect_source
from ocr_app.diagnostic_service import DiagnosticService


class PortableDiagnosticTests(unittest.TestCase):
    def test_import_without_site_packages_and_legacy_error_identity(self):
        backend = Path(__file__).resolve().parents[1] / 'backend'
        result = subprocess.run([sys.executable, '-I', '-S', '-c',
            f"import sys; sys.path.insert(0, {str(backend)!r}); "
            "from ocr_app.diagnostic_service import DiagnosticService; "
            "from ocr_app.diagnostic_offline import collect_source"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        from ocr_app.task_errors import TaskError
        from ocr_app.task_store import TaskError as Legacy
        self.assertIs(TaskError, Legacy)

    def test_readonly_serious_export_does_not_create_lock_or_rewrite_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, OCR_LOG_LEVEL='INFO'):
            root = Path(directory)
            logger = d.init_diagnostics(root, 'runtime')
            logger.exception('runtime_failed', ValueError('PRIVATE'))
            lock = root / '.diagnostic.lock'
            lock.unlink(missing_ok=True)
            before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
            payload, metadata = collect_source(root)
            self.assertFalse(metadata['incomplete'])
            self.assertEqual([json.loads(line)['level'] for line in payload.splitlines()], ['CRITICAL'])
            self.assertFalse(lock.exists())
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()})

    def test_cancelled_history_scan_reports_incomplete_without_claiming_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = d.init_diagnostics(Path(directory), 'runtime')
            logger.event('request_timeout')
            service, stop, issues = DiagnosticService(logger), threading.Event(), ReadIssues()
            stop.set()
            self.assertEqual(list(service.records(stop=stop, issues=issues)), [])
            self.assertEqual(issues.metadata(), dict(incomplete=True, skipped_files=0, skipped_records=0))

    def test_serious_stream_cli_works_without_site_packages_and_preserves_source(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'collect_diagnostics.py'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, OCR_LOG_LEVEL='INFO'):
            root = Path(directory)
            logger = d.init_diagnostics(root, 'runtime')
            logger.event('request_completed')
            logger.event('request_timeout')
            (root / '.diagnostic.lock').unlink(missing_ok=True)
            before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
            result = subprocess.run([sys.executable, '-I', '-S', str(script), '--root', str(root),
                                     '--serious-stream'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
                self.assertIsNone(archive.testzip())
                manifest = json.loads(archive.read('manifest.json'))
                self.assertTrue(manifest['available'])
                self.assertFalse(manifest['incomplete'])
                self.assertEqual(manifest['records'], 1)
                self.assertEqual([json.loads(line)['level'] for line in archive.read('events.jsonl').splitlines()], ['ERROR'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()})
