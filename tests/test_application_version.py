"""Release metadata agrees without requiring historical logs to be rewritten."""
import json
from pathlib import Path
import unittest
import yaml
from ocr_app.version import APP_VERSION
from ocr_app.diagnostics import APP_VERSION as DIAGNOSTIC_VERSION

ROOT=Path(__file__).resolve().parents[1]


class ApplicationVersionTests(unittest.TestCase):
    def test_current_contract_and_frontend_package_match_runtime_version(self):
        self.assertEqual(yaml.safe_load((ROOT/'openapi.yaml').read_text(encoding='utf-8'))['info']['version'],APP_VERSION)
        self.assertEqual(DIAGNOSTIC_VERSION,APP_VERSION)
        self.assertEqual(json.loads((ROOT/'frontend/package.json').read_text(encoding='utf-8'))['version'],APP_VERSION)
        lock=json.loads((ROOT/'frontend/package-lock.json').read_text(encoding='utf-8'))
        self.assertEqual(lock['version'],APP_VERSION)
        self.assertEqual(lock['packages']['']['version'],APP_VERSION)
