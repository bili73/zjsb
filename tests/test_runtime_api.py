import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.api import create_app


class FakeRuntime:
    def __init__(self):
        self.started = 0
        self.closed = 0
        self.alive = True
        self.view = dict(configured_mode='dual_resident', effective_mode=None,
                         state='starting', models={'glm_ocr': 'loading',
                         'paddleocr_vl': 'unloaded'}, reason_code=None)

    def start(self):
        self.started += 1

    def close(self):
        self.closed += 1

    def snapshot(self):
        return copy.deepcopy(self.view)

    def is_alive(self):
        return self.alive


class RuntimeAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = FakeRuntime()
        self.static = self.root / 'dist'
        self.storage = self.root / 'session'

    def client(self, peer='127.0.0.1', static=None, storage=None):
        return TestClient(create_app(self.runtime, static or self.static, storage or self.storage),
                          base_url='http://127.0.0.1', client=(peer, 12345))

    def test_lifecycle_and_health_during_starting_and_ready(self):
        with self.client() as client:
            self.assertEqual(self.runtime.started, 1)
            data = client.get('/health').json()
            self.assertEqual(data['version'], '1.17.3')
            self.assertEqual(data['status'], 'degraded')
            self.assertIsNone(data['queue_depth'])
            self.assertEqual(data['components'], {'db': 'down', 'worker': 'ok', 'storage': 'ok'})
            self.assertEqual(data['runtime']['state'], 'starting')
            self.runtime.view.update(state='ready', effective_mode='dual_resident')
            self.runtime.view['models'] = dict(glm_ocr='ready', paddleocr_vl='ready')
            data = client.get('/health').json()
            self.assertEqual(data['runtime']['state'], 'ready')
            self.assertEqual(data['status'], 'degraded')
            self.runtime.alive = False
            self.assertEqual(client.get('/health').json()['components']['worker'], 'down')
        self.assertEqual(self.runtime.closed, 1)

    def test_storage_probe_once_and_failure_is_reported(self):
        with patch('ocr_app.api.TemporaryFile', wraps=tempfile.TemporaryFile) as probe:
            with self.client() as client:
                client.get('/health')
                client.get('/health')
            self.assertEqual(probe.call_count, 1)
        blocked = self.root / 'file-not-directory'
        blocked.write_text('occupied')
        with self.client(storage=blocked) as client:
            data = client.get('/health').json()
            self.assertEqual(data['components']['storage'], 'down')
            self.assertNotIn(str(blocked), client.get('/health').text)

    def test_runtime_schema_fail_closed_without_exception_details(self):
        invalid = [dict(state='private error'), dict(reason_code='C:/secret/model'),
                   dict(effective_mode='cpu'), dict(configured_mode='invalid'),
                   dict(models={'glm_ocr': 'ready', 'paddleocr_vl': 'invalid'}),
                   dict(private_path='C:/secret/model')]
        with self.client() as client:
            original = copy.deepcopy(self.runtime.view)
            for values in invalid:
                with self.subTest(values=values):
                    self.runtime.view = {**original, **values}
                    response = client.get('/health')
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('runtime', response.json())
                    self.assertEqual(response.json()['components']['worker'], 'down')
                    self.assertNotIn('secret', response.text)
            self.runtime.snapshot = lambda: (_ for _ in ()).throw(RuntimeError('secret-path'))
            self.assertNotIn('secret-path', client.get('/health').text)

    def test_start_failure_still_closes_and_has_no_exception_leak(self):
        self.runtime.start = lambda: (_ for _ in ()).throw(RuntimeError('secret-path'))
        with self.client() as client:
            response = client.get('/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['components']['worker'], 'down')
            self.assertNotIn('secret-path', response.text)
        self.assertEqual(self.runtime.closed, 1)

    def test_loopback_and_host_boundary(self):
        for peer in ['192.168.1.8', 'testclient']:
            with self.subTest(peer=peer), self.client(peer=peer) as client:
                self.assertEqual(client.get('/health', headers={'X-Forwarded-For': '127.0.0.1'}).status_code, 403)
        with self.client() as client:
            for host in ['evil.example', '127.0.0.1.evil.example', 'localhost.evil.example', 'testserver']:
                self.assertEqual(client.get('/health', headers={'Host': host}).status_code, 400)
            for host in ['localhost', 'localhost:8765', '127.0.0.1:8765']:
                self.assertEqual(client.get('/health', headers={'Host': host}).status_code, 200)
            response = client.get('/health', headers={'Origin': 'https://evil.example'})
            self.assertNotIn('access-control-allow-origin', response.headers)

    def test_unbuilt_and_unimplemented_routes(self):
        with self.client() as client:
            self.assertEqual(client.get('/').status_code, 503)
            for path in ['/batches', '/tasks', '/auth/me', '/exit', '/mode', '/inference', '/docs', '/openapi.json']:
                self.assertEqual(client.get(path).status_code, 404)

    def test_static_files_and_unknown_business_route(self):
        self.static.mkdir()
        (self.static / 'assets').mkdir()
        (self.static / 'index.html').write_text('<html>Local OCR</html>', encoding='utf-8')
        (self.static / 'assets/app.js').write_text('const ready = true;', encoding='utf-8')
        with self.client() as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertIn('Local OCR', client.get('/').text)
            self.assertEqual(client.get('/assets/app.js').text, 'const ready = true;')
            self.assertEqual(client.get('/batches').status_code, 404)
            self.assertEqual(client.get('/health').status_code, 200)


if __name__ == '__main__':
    unittest.main()
