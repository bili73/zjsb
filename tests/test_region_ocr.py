"""Synthetic corrected sources and isolated HTTP stores; no production/model calls."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from sqlalchemy import text
import test_review_api as base
from ocr_app import region_ocr
from ocr_app.task_store import TaskError


class RegionOCRTests(unittest.TestCase):
    setUp = base.ReviewAPITests.setUp
    upload = base.ReviewAPITests.upload
    task = base.ReviewAPITests.task
    ready = base.ReviewAPITests.ready
    submit = base.ReviewAPITests.submit
    result = base.ReviewAPITests.result

    def request(self, task, **changes):
        body = dict(run_id=task['run_id'], expected_revision=task['result_revision'], page=1,
                    field_key='certificate_no', bbox=[0, 0, 1, 1])
        body.update(changes)
        return self.client.post(f"/api/v1/tasks/{task['task_id']}/ocr-region", headers=self.headers, json=body)

    def test_text_only_response_preserves_number_zeros_and_result_and_run(self):
        task, _ = self.ready()
        before = self.result(task)
        with self.business.engine.connect() as c:
            run_before = dict(c.execute(text('SELECT * FROM runs WHERE id=:id'), {'id': task['run_id']}).mappings().one())
        def recognize(data):
            with Image.open(BytesIO(data)) as image:
                self.assertEqual(image.size, (16, 12))
            return dict(text='001234567890123456', confidence=.93)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            response = self.request(task)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        from test_document_contract import DocumentContractTests
        DocumentContractTests.setUpClass()
        DocumentContractTests().validate('RegionOCRResult', payload)
        self.assertEqual(payload['text'], '001234567890123456')
        self.assertEqual((payload['field_key'], payload['page'], payload['result_revision']), ('certificate_no', 1, task['result_revision']))
        self.assertEqual(self.result(task), before)
        with self.business.engine.connect() as c:
            self.assertEqual(dict(c.execute(text('SELECT * FROM runs WHERE id=:id'), {'id': task['run_id']}).mappings().one()), run_before)
            self.assertNotIn(payload['text'], '\n'.join(c.execute(text('SELECT detail_json FROM audit')).scalars()))

    def test_scaled_normalized_crop_uses_correct_pixels_and_rejects_invalid_boxes(self):
        buffer = BytesIO()
        image = Image.new('RGB', (200, 100), 'red')
        image.paste('blue', (50, 20, 150, 80)); image.save(buffer, format='PNG')
        with Image.open(BytesIO(region_ocr.crop_region(buffer.getvalue(), [.25, .2, .75, .8]))) as crop:
            self.assertEqual(crop.size, (100, 60)); self.assertEqual(crop.getpixel((0, 0)), (0, 0, 255))
        for box in ([0, 0, 0, 1], [1, 0, 0, 1], [-.1, 0, 1, 1], [0, 0, 2, 1], [0, 0, .01, .01], [False, 0, 1, 1], [0, 0, float('nan'), 1]):
            with self.subTest(box=box), self.assertRaises(TaskError):
                region_ocr.crop_region(buffer.getvalue(), box)
        large = BytesIO(); Image.new('RGB', (2000, 2000)).save(large, format='PNG')
        with self.assertRaises(TaskError): region_ocr.crop_region(large.getvalue(), [0, 0, 1, 1])

    def test_general_transcription_without_a_field_keeps_multiline_text_and_saved_results(self):
        from test_document_contract import DocumentContractTests
        DocumentContractTests.setUpClass()
        for kind in ['DIPLOMA', 'MEDICAL_REPORT', 'GENERIC', 'HOUSEHOLD_REGISTER']:
            task, _ = self.ready(kind); before = self.result(task)
            for legacy in [{}, {'field_key': None}]:
                body = dict(run_id=task['run_id'], expected_revision=task['result_revision'], page=1, bbox=[0, 0, 1, 1], **legacy)
                DocumentContractTests().validate('RegionOCRRequest', body)
                with patch.object(region_ocr, 'recognize_crop', return_value=dict(text='00123\n合成文字', confidence=.9)):
                    response = self.client.post(f"/api/v1/tasks/{task['task_id']}/ocr-region", headers=self.headers, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIsNone(response.json()['field_key'])
                self.assertEqual(response.json()['text'], '00123\n合成文字')
                DocumentContractTests().validate('RegionOCRResult', response.json())
                self.assertEqual(self.result(task), before)

    def test_invalid_fields_versions_and_pages_never_call_ocr(self):
        task, _ = self.ready()
        with patch.object(region_ocr, 'recognize_crop') as engine:
            for change, status in [({'field_key': 'principal'}, 422), ({'field_key': 'gender'}, 422),
                ({'expected_revision': task['result_revision'] + 1}, 409), ({'run_id': str(uuid4())}, 409),
                ({'page': 2}, 404), ({'page': True}, 422), ({'bbox': [False, 0, 1, 1]}, 422),
                ({'bbox': [0, 0, 0, 1]}, 422), ({'extra': 'PRIVATE_INVALID_VALUE'}, 422)]:
                with self.subTest(change=change):
                    response = self.request(task, **change)
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertNotIn('PRIVATE_INVALID_VALUE', response.text)
            engine.assert_not_called()
        medical, _ = self.ready('MEDICAL_REPORT')
        with patch.object(region_ocr, 'recognize_crop') as engine:
            self.assertEqual(self.request(medical, field_key='exam_project_count').status_code, 422)
            engine.assert_not_called()

    def test_foreign_operator_viewer_and_anonymous_cannot_read_crop(self):
        task, _ = self.ready()
        old = self.headers
        with patch.object(region_ocr, 'recognize_crop') as engine:
            for role, expected in [('operator', 404), ('viewer', 403), ('admin', 200)]:
                key = 'synthetic-region-key-' + role
                self.business.accounts.accounts.append(dict(user_id=str(uuid4()), display_name=role, role=role, key=key))
                self.headers = {'X-API-Key': key}
                engine.return_value = dict(text='synthetic', confidence=.8)
                for field in ['certificate_no', None]:
                    self.assertEqual(self.request(task, field_key=field).status_code, expected)
            self.headers = {}
            self.assertEqual(self.request(task).status_code, 401)
            self.assertEqual(engine.call_count, 2)
        self.headers = old

    def test_revision_change_during_ocr_discards_text(self):
        task, _ = self.ready()
        def recognize(_):
            self.assertEqual(self.submit(task, fields={'name': 'Changed'}).status_code, 200)
            return dict(text='PRIVATE_LATE_OCR_VALUE', confidence=.9)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            response = self.request(task)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn('PRIVATE_LATE_OCR_VALUE', response.text)

    def test_pdf_second_corrected_page_is_used(self):
        import fitz
        pdf = fitz.open(); pdf.new_page(); pdf.new_page()
        response = self.client.post('/api/v1/batches', headers=self.headers, data={'doc_type_hint': 'DIPLOMA'},
                                    files=[('files', ('synthetic.pdf', pdf.tobytes(), 'application/pdf'))])
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()['task_ids'][0]
        store = self.business.store; worker = store.claim_next(); pages = []
        for index, color in [(1, 'red'), (2, 'blue')]:
            buffer = BytesIO(); Image.new('RGB', (80, 60), color).save(buffer, format='PNG')
            page_id = store.save_page(worker, index, buffer.getvalue(), 80, 60)
            pages.append(dict(page_id=page_id, page_index=index, width=80, height=60, regions=[]))
        result = base.extract_result([], 'DIPLOMA'); result.update(pages=pages, status='NEED_REVIEW')
        self.assertTrue(store.publish(worker, result)); task = self.task(identifier)
        self.assertEqual(task['actual_source_page_count'], 2)
        def recognize(data):
            with Image.open(BytesIO(data)) as image: self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            return dict(text='page two', confidence=.9)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            self.assertEqual(self.request(task, page=2).json()['text'], 'page two')

    def test_deletion_during_ocr_discards_text(self):
        task, _ = self.ready()
        def recognize(_):
            self.business.store.delete_batch(task['batch_id'], [dict(task_id=task['task_id'], run_id=task['run_id'], expected_revision=task['result_revision'])], 'synthetic', authorize=lambda c: None)
            return dict(text='PRIVATE_DELETED_VALUE', confidence=.9)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            response = self.request(task)
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn('PRIVATE_DELETED_VALUE', response.text)

    def test_cookie_csrf_and_disable_during_ocr(self):
        self.business.accounts.set_user('regionuser', 'Synthetic password only', 'Test user', 'operator')
        login = self.client.post('/api/v1/auth/login', json={'username': 'regionuser', 'password': 'Synthetic password only'}, headers={'Origin': 'http://127.0.0.1'})
        self.headers = {'Origin': 'http://127.0.0.1', 'X-CSRF-Token': login.json()['csrf_token']}
        task, _ = self.ready()
        saved = self.headers
        self.headers = {'Origin': 'http://127.0.0.1'}
        with patch.object(region_ocr, 'recognize_crop') as engine:
            self.assertEqual(self.request(task).status_code, 403); engine.assert_not_called()
        self.headers = saved
        def recognize(_):
            self.business.accounts.disable_user('regionuser')
            return dict(text='PRIVATE_REVOKED_VALUE', confidence=.9)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            response = self.request(task)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn('PRIVATE_REVOKED_VALUE', response.text)

    def test_new_login_during_ocr_discards_text(self):
        password = 'Synthetic password only'
        self.business.accounts.set_user('regionuser', password, 'Test user', 'operator')
        login = self.client.post('/api/v1/auth/login', json={'username': 'regionuser', 'password': password}, headers={'Origin': 'http://127.0.0.1'})
        self.headers = {'Origin': 'http://127.0.0.1', 'X-CSRF-Token': login.json()['csrf_token']}
        task, _ = self.ready()
        def recognize(_):
            new_token = self.business.accounts.login('regionuser', password, '127.0.0.1')
            self.assertIsNotNone(self.business.accounts.session(new_token))
            return dict(text='PRIVATE_OLD_SESSION_VALUE', confidence=.9)
        with patch.object(region_ocr, 'recognize_crop', side_effect=recognize):
            response = self.request(task)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn('PRIVATE_OLD_SESSION_VALUE', response.text)

    @unittest.skipUnless(os.name == 'nt', 'native Windows worker transport')
    def test_binary_transport_drains_stderr_and_bounds_fragmented_output(self):
        worker = self.root / 'region_ocr_worker.py'
        data = bytes(range(256)) * 512
        worker.write_text('''import json, sys, time
assert sys.stdin.buffer.read() == bytes(range(256)) * 512
sys.stderr.buffer.write(b'x' * 131072); sys.stderr.buffer.flush()
result = json.dumps(dict(text='00123\\n合成文字', confidence=.9)).encode('ascii')
sys.stdout.buffer.write(result[:12]); sys.stdout.buffer.flush()
time.sleep(.03)
sys.stdout.buffer.write(result[12:]); sys.stdout.buffer.flush()
''', encoding='utf-8')
        with patch.object(region_ocr, '__file__', str(self.root / 'region_ocr.py')):
            self.assertEqual(region_ocr.recognize_crop(data), dict(text='00123\n合成文字', confidence=.9))
            worker.write_text("import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x' * 40000)", encoding='utf-8')
            with self.assertRaises(TaskError) as error:
                region_ocr.recognize_crop(data)
            self.assertEqual(error.exception.code, 'REGION_OCR_UNAVAILABLE')
        self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()

    @unittest.skipUnless(os.name == 'nt', 'native Windows worker cleanup')
    def test_cleanup_failure_blocks_future_workers_until_restart(self):
        worker = self.root / 'region_ocr_worker.py'
        worker.write_text('import sys; sys.stdin.buffer.read(); print(\'{"text":"00123","confidence":0.9}\')', encoding='utf-8')
        factory = region_ocr.JobProcess
        def cleanup_failure(*args, **kwargs):
            process = factory(*args, **kwargs)
            close = process.close
            def fail_close():
                close()  # Actually reclaim every synthetic process before injecting failure.
                raise TimeoutError('synthetic exit confirmation failure')
            process.close = fail_close
            return process
        with patch.object(region_ocr, '__file__', str(self.root / 'region_ocr.py')), \
                patch.object(region_ocr, '_cleanup_failed', False), \
                patch.object(region_ocr, 'JobProcess', side_effect=cleanup_failure) as spawn:
            for _ in range(2):
                with self.assertRaises(TaskError) as error:
                    region_ocr.recognize_crop(b'crop')
                self.assertEqual(error.exception.code, 'REGION_OCR_UNAVAILABLE')
                self.assertIn('重启后端', error.exception.message)
            self.assertEqual(spawn.call_count, 1)
            self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()

    @unittest.skipUnless(os.name == 'nt', 'Windows virtualenv redirector regression')
    def test_timeout_reaps_actual_worker_and_descendants_before_releasing_slot(self):
        import psutil
        identities = self.root / 'owned-processes.json'
        worker = self.root / 'region_ocr_worker.py'
        worker.write_text('''import json, os, subprocess, sys, time
from pathlib import Path
import psutil
child = subprocess.Popen([sys._base_executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)
me = psutil.Process()
root = me.parent() if sys.argv[0] in me.parent().cmdline() else me
owned = [root, *root.children(recursive=True)]
Path(sys.argv[0]).with_name('owned-processes.json').write_text(json.dumps([
    dict(pid=p.pid, created=p.create_time()) for p in owned]))
time.sleep(60)
''', encoding='utf-8')
        def owned_processes():
            processes = []
            for identity in json.loads(identities.read_text()):
                try:
                    process = psutil.Process(identity['pid'])
                    if process.create_time() == identity['created']:
                        processes.append(process)
                except psutil.NoSuchProcess:
                    pass
            return processes
        try:
            started = time.monotonic()
            with patch.object(region_ocr, '__file__', str(self.root / 'region_ocr.py')), patch.object(region_ocr, 'TIMEOUT_SECONDS', 1.5):
                with self.assertRaises(TaskError) as error:
                    region_ocr.recognize_crop(b'synthetic crop')
            self.assertEqual(error.exception.code, 'REGION_OCR_TIMEOUT')
            self.assertLess(time.monotonic() - started, 7)
            self.assertTrue(identities.exists(), 'synthetic worker must start before timing out')
            self.assertGreaterEqual(len(json.loads(identities.read_text())), 2)
            # Job accounting reaches zero before every terminated process object
            # becomes signaled; PID visibility alone is not an exit-state check.
            _, alive = psutil.wait_procs(owned_processes(), timeout=5)
            self.assertEqual([p.pid for p in alive], [])
            self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()
        finally:
            if identities.exists():
                processes = owned_processes()
                for process in reversed(processes):
                    try: process.kill()
                    except psutil.NoSuchProcess: pass
                psutil.wait_procs(processes, timeout=3)

    def test_busy_timeout_empty_and_failure_release_single_slot(self):
        region_ocr._slot.acquire()
        try:
            with self.assertRaises(TaskError) as error: region_ocr.recognize_crop(b'crop')
            self.assertEqual(error.exception.code, 'REGION_OCR_BUSY')
        finally: region_ocr._slot.release()
        for outcome, code in [(TimeoutError('synthetic timeout'), 'REGION_OCR_TIMEOUT'),
            (subprocess.CompletedProcess([], 1, b''), 'REGION_OCR_UNAVAILABLE'),
            (subprocess.CompletedProcess([], 0, b'bad json'), 'REGION_OCR_UNAVAILABLE'),
            (subprocess.CompletedProcess([], 0, b'{"text":"","confidence":0}'), 'REGION_OCR_EMPTY')]:
            with self.subTest(code=code), patch.object(region_ocr, '_run_crop', **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})):
                with self.assertRaises(TaskError) as error: region_ocr.recognize_crop(b'crop')
                self.assertEqual(error.exception.code, code)
                self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()
        with patch.object(region_ocr, '_run_crop', return_value=subprocess.CompletedProcess([], 0, b'{"text":"00123","confidence":0.9}')):
            self.assertEqual(region_ocr.recognize_crop(b'crop')['text'], '00123')


if __name__ == '__main__':
    unittest.main()
