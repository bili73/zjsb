"""Synthetic corrected sources and isolated HTTP stores; no production/model calls."""
from io import BytesIO
import json
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

    def test_real_timed_out_child_is_reaped(self):
        import psutil
        popen = subprocess.Popen; children = []
        def sleeping_child(*args, **kwargs):
            child = popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(child); return child
        started = time.monotonic()
        with patch.object(region_ocr.subprocess, 'Popen', side_effect=sleeping_child), patch.object(region_ocr, 'TIMEOUT_SECONDS', .2):
            with self.assertRaises(TaskError) as error: region_ocr.recognize_crop(b'crop')
        self.assertEqual(error.exception.code, 'REGION_OCR_TIMEOUT')
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertFalse(psutil.pid_exists(children[0].pid))
        self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()

    def test_busy_timeout_empty_and_failure_release_single_slot(self):
        region_ocr._slot.acquire()
        try:
            with self.assertRaises(TaskError) as error: region_ocr.recognize_crop(b'crop')
            self.assertEqual(error.exception.code, 'REGION_OCR_BUSY')
        finally: region_ocr._slot.release()
        for outcome, code in [(subprocess.TimeoutExpired('synthetic', 10), 'REGION_OCR_TIMEOUT'),
            (subprocess.CompletedProcess([], 1, b''), 'REGION_OCR_UNAVAILABLE'),
            (subprocess.CompletedProcess([], 0, b'bad json'), 'REGION_OCR_UNAVAILABLE'),
            (subprocess.CompletedProcess([], 0, b'{"text":"","confidence":0}'), 'REGION_OCR_EMPTY')]:
            with self.subTest(code=code), patch.object(region_ocr.subprocess, 'run', **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})) as run:
                with self.assertRaises(TaskError) as error: region_ocr.recognize_crop(b'crop')
                self.assertEqual(error.exception.code, code)
                self.assertEqual(run.call_args.kwargs['timeout'], 10)
                self.assertTrue(region_ocr._slot.acquire(blocking=False)); region_ocr._slot.release()
        with patch.object(region_ocr.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"text":"00123","confidence":0.9}')):
            self.assertEqual(region_ocr.recognize_crop(b'crop')['text'], '00123')


if __name__ == '__main__':
    unittest.main()
