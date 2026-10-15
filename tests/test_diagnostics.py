"""CPU-only privacy, retention, process-reload and memory-input regressions."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app import diagnostics as d
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, ModelProcess


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'OCR_LOG_LEVEL': 'INFO'}))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_allowlist_ids_and_exception_remove_sensitive_values(self):
        secret = '6222021234567890123'
        task_id = str(uuid.uuid4())
        logger = d.init_diagnostics(self.root / 'logs', 'model', 'session')
        try:
            private_local = secret
            raise ValueError('C:/private/' + private_local + '.png')
        except Exception as error:
            error_id = logger.exception('request_failed', error, task_id=task_id,
                                        request_id=secret, raw_text=secret, image=secret, api_key=secret,
                                        model='glm_ocr', error_code='INPUT_INVALID', pid=int(secret))
        text = logger.path.read_text(encoding='utf-8')
        self.assertNotIn(secret, text)
        self.assertNotIn('C:/private', text)
        self.assertNotIn('private_local', text)
        row = json.loads(text.splitlines()[-1])
        self.assertEqual(row['context']['task_id'], task_id)
        self.assertEqual(row['context']['error_id'], error_id)
        self.assertEqual(row['exceptions'][0]['type'], 'ValueError')
        self.assertTrue(row['exceptions'][0]['frames'])
        self.assertEqual(d.opaque_id(row['context']['request_id']), row['context']['request_id'])

    def test_rotation_is_five_files_and_new_instances_do_not_overwrite(self):
        with patch.object(d, 'MAX_BYTES', 1000):
            first = d.init_diagnostics(self.root, 'model', 'same-session')
            for _ in range(30):
                first.event('request_completed', model='glm_ocr', output_tokens=48)
            files = list(self.root.glob(first.path.name + '*'))
            self.assertEqual(len(files), 5)
            self.assertTrue(all(path.stat().st_size <= 1000 for path in files))
            previous = {path.name: path.read_bytes() for path in files}
            second = d.init_diagnostics(self.root, 'model', 'same-session')
            self.assertNotEqual(first.path, second.path)
            for name, content in previous.items():
                self.assertEqual((self.root / name).read_bytes(), content)

    def test_retention_only_deletes_owned_direct_files(self):
        logger = d.init_diagnostics(self.root, 'runtime')
        old = time.time() - 8 * 86400
        os.utime(logger.path, (old, old))
        legacy = self.root / 'runtime.stderr.log'
        legacy.write_text('legacy-private', encoding='utf-8')
        os.utime(legacy, (old, old))
        nested = self.root / 'materials'
        nested.mkdir()
        material = nested / logger.path.name
        material.write_text('private', encoding='utf-8')
        os.utime(material, (old, old))
        d.init_diagnostics(self.root, 'client')
        from ocr_app.diagnostic_archive import maintenance, owned_archives
        maintenance(self.root)
        self.assertFalse(logger.path.exists())
        self.assertEqual(len(owned_archives(self.root)), 1)
        self.assertTrue(legacy.exists())
        self.assertTrue(material.exists())

    def test_collector_revalidates_and_never_copies_legacy_or_secrets(self):
        logs = self.root / 'diagnostics'
        logger = d.init_diagnostics(logs, 'api')
        logger.event('request_completed', duration_seconds=.5)
        row = json.loads(logger.path.read_text().splitlines()[0])
        row.update(raw_text='RAW_MATERIAL_SECRET', settings='API_KEY_SECRET')
        row['context'] = {'image': 'RAW_MATERIAL_SECRET', 'raw_text': 'RAW_MATERIAL_SECRET'}
        with logger.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\nnot-json-secret\n')
        for name in ('.env', 'settings.json', 'runtime.stderr.log', 'card.png'):
            (logs / name).write_text('API_KEY_SECRET', encoding='utf-8')
        destination = self.root / 'safe.zip'
        manifest = d.collect_diagnostics(logs, destination)
        with zipfile.ZipFile(destination) as archive:
            content = b'\n'.join(archive.read(name) for name in archive.namelist()).decode()
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'logs/' + logger.path.name})
        self.assertNotIn('SECRET', content)
        self.assertNotIn('not-json', content)
        self.assertEqual(manifest['skipped_lines'], 1)
        with self.assertRaises(FileExistsError):
            d.collect_diagnostics(logs, destination)

    def test_logging_failure_is_visible_without_disclosing_path_or_raising(self):
        blocked = self.root / 'private-card-number'
        blocked.write_text('not a directory')
        capture = io.StringIO()
        with patch('sys.stderr', capture):
            logger = d.init_diagnostics(blocked, 'runtime')
            error_id = logger.exception('close_failed', RuntimeError('secret'), raw_text='secret')
            logger.event('close_completed')
            logger.close()
        self.assertFalse(logger.available)
        self.assertTrue(error_id.startswith('e_'))
        self.assertIn('DIAGNOSTICS_UNAVAILABLE', capture.getvalue())
        self.assertNotIn('private-card-number', capture.getvalue())
        self.assertNotIn('secret', capture.getvalue())

    def test_export_cli_works_with_no_service(self):
        logs = self.root / 'logs'
        d.init_diagnostics(logs, 'bootstrap').event('bootstrap_failed')
        out = self.root / 'offline.zip'
        process = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/collect_diagnostics.py'),
                                  '--root', str(logs), '--output', str(out)], capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(out.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows Job supervision')
    def test_restarted_fake_models_preserve_logs_and_discard_raw_stderr(self):
        class FakeConfig(RuntimeConfig):
            def model_command(self, key):
                return [sys.executable, '-u', '-c',
                        "import json,sys; print('RAW_MATERIAL_SECRET',file=sys.stderr,flush=True); "
                        "[(print(json.dumps({'id':json.loads(line)['id'],'ok':True,'result':{}}),flush=True)) for line in sys.stdin]"]
        for _ in range(2):
            process = ModelProcess('glm_ocr', FakeConfig(self.root), lambda *args: None)
            try:
                self.assertEqual(process.call('load', timeout=3), {})
            finally:
                process.close()
        files = list((self.root / 'diagnostics').glob('*.jsonl'))
        self.assertEqual(len(files), 2)
        content = '\n'.join(path.read_text(encoding='utf-8') for path in files)
        self.assertNotIn('RAW_MATERIAL_SECRET', content)
        self.assertIn('spawn_completed', content)
        self.assertFalse(list(self.root.glob('*.stderr.log')))

    def test_manager_forwards_memory_image_and_safe_correlation(self):
        client = Mock()
        client.call.return_value = {'text': 'MATERIAL_SECRET'}
        client.poll.return_value = None
        manager = ModelManager(RuntimeConfig(self.root), factory=Mock())
        manager.clients['glm_ocr'] = client
        manager.view['models']['glm_ocr'] = 'ready'
        task_id = str(uuid.uuid4())
        result = manager.recognize('glm_ocr', image_base64='PRIVATE_IMAGE', context={'task_id': task_id, 'raw_text': 'PRIVATE'})
        self.assertEqual(result['text'], 'MATERIAL_SECRET')
        payload = client.call.call_args.kwargs
        self.assertEqual(payload['image_base64'], 'PRIVATE_IMAGE')
        self.assertNotIn('image', payload)
        self.assertEqual(payload['context'], {'task_id': task_id})
        content = manager.diag.path.read_text(encoding='utf-8')
        self.assertNotIn('MATERIAL_SECRET', content)
        self.assertNotIn('PRIVATE', content)
        manager.close()

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow is required for CPU image decoding')
    def test_base64_and_path_inputs_are_equivalent_without_image_writes(self):
        from PIL import Image
        from model_worker import Engine
        buffer = io.BytesIO()
        Image.new('RGB', (12, 8), 'white').save(buffer, format='PNG')
        data = buffer.getvalue()
        engine = Engine('glm-ocr')
        engine.model = object()
        engine.generate = lambda image, task, tokens: dict(size=image.size, mode=image.mode)
        with patch('builtins.open', side_effect=AssertionError('No disk image writes or reads')):
            memory = engine.recognize({'image_base64': base64.b64encode(data).decode(), 'task': 'ocr'})
        file = self.root / 'synthetic.png'
        file.write_bytes(data)
        self.assertEqual(memory, engine.recognize({'image': str(file), 'task': 'ocr'}))
        with self.assertRaises(ValueError):
            engine.recognize({'image_base64': '@@not-base64', 'task': 'ocr'})
        with self.assertRaises(ValueError):
            engine.recognize({'image': str(file), 'image_base64': 'AA==', 'task': 'ocr'})


if __name__ == '__main__':
    unittest.main()
