"""Authenticated local HTTP tests with encrypted temporary storage and no GPU."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.api import create_app
from ocr_app.business import Business


class FakeRuntime:
    def __init__(self):
        self.alive = True
        self.started = self.closed = 0

    def start(self):
        self.started += 1

    def close(self, graceful=True):
        self.closed += 1
        self.alive = False

    def is_alive(self):
        return self.alive

    def snapshot(self):
        return dict(configured_mode='dual_resident', effective_mode='dual_resident', state='ready',
                    models=dict(glm_ocr='ready', paddleocr_vl='ready'), reason_code=None)

    def request(self, *args, **kwargs):
        raise AssertionError('HTTP upload must not trigger synchronous OCR')


class BusinessAPITests(unittest.TestCase):
    def test_batch_names_derive_from_types_without_rewriting_history(self):
        from sqlalchemy import text
        created = self.upload().json()
        identifier = created['batch_id']
        with self.business.store.transaction() as connection:
            saved = connection.execute(text('SELECT name_enc FROM batches WHERE id=:id'), {'id': identifier}).scalar_one()
            self.assertEqual(self.business.storage.unpack(saved), '毕业证')
            historical = self.business.storage.pack('上传批次')
            connection.execute(text('UPDATE batches SET name_enc=:name WHERE id=:id'), dict(id=identifier, name=historical))
        batch = self.business.store.batch(identifier)
        self.assertEqual((batch['name'], batch['display_name']), ('毕业证', '毕业证'))
        with self.business.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT name_enc FROM batches WHERE id=:id'), {'id': identifier}).scalar_one(), historical)
        with patch.object(self.business.store, 'tasks', return_value=[{'doc_type': 'DIPLOMA', 'status': 'COMPLETED', 'updated_at': batch['created_at']}, {'doc_type': 'DEGREE_CERT', 'status': 'COMPLETED', 'updated_at': batch['created_at']} ]):
            self.assertEqual(self.business.store.batch(identifier)['name'], '混合材料 · 毕业证 / 学位证')
        with patch.object(self.business.store, 'tasks', return_value=[]):
            self.assertEqual(self.business.store.batch(identifier)['name'], '待确定类型')

    def test_batches_are_descending_and_timestamps_remain_utc(self):
        # Equal wall-clock ticks use the documented ID tie-break, not upload order.
        with patch('ocr_app.task_store.now', return_value='2026-10-09T00:00:00+00:00'):
            first = self.upload().json()['batch_id']
        with patch('ocr_app.task_store.now', return_value='2026-10-10T00:00:00+00:00'):
            second = self.upload('DEGREE_CERT').json()['batch_id']
        listed = self.business.store.batches()['items']
        self.assertEqual([item['batch_id'] for item in listed], [second, first])
        self.assertTrue(all(item['created_at'].endswith('+00:00') for item in listed))

    def test_batch_date_range_uses_shanghai_days_before_count_and_pagination(self):
        from sqlalchemy import text
        times=['2026-10-08T15:59:59+00:00','2026-10-08T16:00:00+00:00',
               '2026-10-09T15:59:59+00:00','2026-10-09T16:00:00+00:00']
        ids=[]
        for timestamp in times:
            identifier=self.upload().json()['batch_id'];ids.append(identifier)
            with self.business.store.transaction() as connection:
                connection.execute(text('UPDATE batches SET created_at=:at WHERE id=:id'),dict(at=timestamp,id=identifier))
        query='/api/v1/batches?date_from=2026-10-09&date_to=2026-10-09&page_size=1'
        first=self.client.get(query,headers=self.headers).json()
        second=self.client.get(query+'&page=2',headers=self.headers).json()
        self.assertEqual(first['total'],2)
        self.assertEqual([b['batch_id'] for b in first['items']],[ids[2]])
        self.assertEqual([b['batch_id'] for b in second['items']],[ids[1]])
        self.assertEqual(self.client.get('/api/v1/batches',headers=self.headers).json()['total'],4)
        lower=self.client.get('/api/v1/batches?date_from=2026-10-10',headers=self.headers).json()
        self.assertEqual([b['batch_id'] for b in lower['items']],[ids[3]])
        upper=self.client.get('/api/v1/batches?date_to=2026-10-08',headers=self.headers).json()
        self.assertEqual([b['batch_id'] for b in upper['items']],[ids[0]])

    def test_batch_date_range_rejects_invalid_reversed_and_unsupported_bounds(self):
        for query in ['date_from=2026-02-30','date_from=invalid',
                      'date_from=2026-10-10&date_to=2026-10-09',
                      'date_from=0001-01-01','date_to=9999-12-31']:
            with self.subTest(query=query):
                self.assert_error(self.client.get('/api/v1/batches?'+query,headers=self.headers),422)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.business = Business(self.root / 'data', key=b'T' * 32)
        self.addCleanup(self.business.close)
        self.runtime = FakeRuntime()
        self.app = create_app(self.runtime, self.root / 'dist', self.root / 'session', business=self.business)
        self.client = self.enterContext(TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)))
        self.headers = {'X-API-Key': self.business.accounts.current_key()}
        buffer = io.BytesIO()
        Image.new('RGB', (16, 12), 'white').save(buffer, format='PNG')
        self.image = buffer.getvalue()

    def upload(self, doc_type='DIPLOMA', *, headers=None, data=None, count=1, abnormal_only=False):
        files = [('files', (f'synthetic-{index}.png', self.image if data is None else data, 'image/png'))
                 for index in range(count)]
        return self.client.post('/api/v1/batches', headers=self.headers if headers is None else headers,
                                data=dict(doc_type_hint=doc_type, abnormal_only=str(abnormal_only).lower()), files=files)

    def task(self, task_id):
        response = self.client.get(f'/api/v1/tasks/{task_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_real_worker_progress_is_queryable_with_retries_and_valid_schema(self):
        import jsonschema
        import yaml
        import runtime_worker
        from test_pipeline_schema import json_schema
        document = json_schema(yaml.safe_load((Path(__file__).resolve().parents[1] / 'openapi.yaml').read_text(encoding='utf-8')))
        validator = jsonschema.Draft7Validator(dict(document, **{'$ref': '#/components/schemas/TaskProgressDetail'}),
                                              format_checker=jsonschema.FormatChecker())
        created = self.upload().json()
        task_id = created['task_ids'][0]
        initial = self.task(task_id)
        claimed = self.business.store.claim_next()
        snapshots = []
        def recognize(*args, **kwargs):
            snapshots.append(self.task(task_id))
            return dict(text='姓名：合成姓名', termination_reason='token_limit' if len(snapshots) < 3 else 'eos')
        manager = Mock(metrics=[], recognize=Mock(side_effect=recognize))
        logger = Mock()
        with patch('ocr_app.pipeline.split_regions', return_value=[(0, 0, 8, 12), (8, 0, 16, 12)]):
            runtime_worker.process_task(self.business.store, manager, claimed, logger)
        logger.exception.assert_not_called()
        self.assertEqual([row['progress_detail']['processed_regions'] for row in snapshots], [0, 0, 0, 1])
        for current in snapshots:
            validator.validate(current['progress_detail'])
            self.assert_task_contract(current)
            self.assertEqual(current['run_id'], initial['run_id'])
            self.assertEqual(current['result_revision'], initial['result_revision'])
            detail = current['progress_detail']
            self.assertEqual((detail['stage'], detail['prepared_pages'], detail['total_pages'], detail['total_regions']),
                             ('OCR', 1, 1, 2))
        finished = self.task(task_id)
        validator.validate(finished['progress_detail'])
        self.assert_task_contract(finished)
        self.assertEqual(finished['status'], 'NEED_REVIEW')
        self.assertEqual(finished['progress'], 100)
        self.assertEqual(finished['progress_detail']['processed_regions'], 2)
        self.assertEqual(finished['progress_detail']['incomplete_regions'], 0)
        self.assertNotIn('_preparation_complete', json.dumps(finished))
        listed = self.client.get(f"/api/v1/batches/{created['batch_id']}/tasks", headers=self.headers).json()
        self.assertEqual(listed[0]['progress_detail'], finished['progress_detail'])
        self.assertEqual(self.client.get('/api/v1/tasks', headers=self.headers).json()['items'][0]['progress_detail'],
                         finished['progress_detail'])

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertIsInstance(body.get('code'), str)
        self.assertIsInstance(body.get('message'), str)
        self.assertTrue(body.get('error_id'))
        self.assertEqual(body.get('request_id'), response.headers.get('X-Request-ID'))
        uuid.UUID(body['request_id'])
        self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
        return body

    def assert_task_contract(self, task):
        required = {'task_id', 'run_id', 'result_revision', 'cancel_requested', 'page_count', 'pages', 'status'}
        self.assertTrue(required <= task.keys())
        uuid.UUID(task['task_id'])
        uuid.UUID(task['run_id'])
        self.assertIs(type(task['result_revision']), int)
        self.assertGreaterEqual(task['result_revision'], 0)
        self.assertIs(type(task['cancel_requested']), bool)
        self.assertEqual(task['page_count'], len(task['pages']))
        self.assertIn(task['status'], {'QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING',
                                     'NEED_REVIEW', 'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'})
        self.assertIsNone(task['doc_type_confidence'])
        self.assertEqual(task['doc_type_confidence_method'], 'unavailable')

    def test_missing_or_invalid_auth_is_401_without_creating_data(self):
        for headers in ({}, {'X-API-Key': 'wrong-key-not-valid-000000000'}):
            with self.subTest(headers=bool(headers)):
                self.assert_error(self.client.get('/api/v1/tasks', headers=headers), 401)
                self.assert_error(self.upload(headers=headers), 401)
        self.assertEqual(self.business.store.tasks(), [])
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_viewer_can_read_but_cannot_upload_cancel_or_rerun(self):
        self.business.accounts.accounts.append(dict(user_id=str(uuid.uuid4()), display_name='Test viewer',
                                                    role='viewer', key='test-viewer-key-01234567890123456789'))
        viewer = {'X-API-Key': 'test-viewer-key-01234567890123456789'}
        created = self.upload().json()
        task_id = created['task_ids'][0]
        task = self.task(task_id)
        self.assertEqual(self.client.get('/api/v1/tasks', headers=viewer).status_code, 200)
        self.assert_error(self.upload(headers=viewer), 403)
        for operation in ('cancel', 'rerun'):
            response = self.client.post(f'/api/v1/tasks/{task_id}/{operation}', headers=viewer,
                                        json=dict(run_id=task['run_id'], expected_revision=task['result_revision']))
            self.assert_error(response, 403)
        me = self.client.get('/api/v1/auth/me', headers=viewer).json()
        self.assertEqual(me['role'], 'viewer')
        self.assertNotIn('key', me)

    def test_bank_full_photo_is_queued_and_original_is_encrypted(self):
        raw = io.BytesIO()
        Image.new('RGB', (850, 540), 'white').save(raw, format='PNG')
        with patch.object(self.business.storage, 'put', wraps=self.business.storage.put) as put:
            response = self.upload('BANK_CARD', data=raw.getvalue())
            self.assertEqual(response.status_code, 202, response.text)
            put.assert_called_once()
        task_id = response.json()['task_ids'][0]
        self.assertEqual(self.task(task_id)['status'], 'QUEUED')
        worker = self.business.store.claim_next()
        self.assertEqual(self.business.storage.read(worker['input_ref']), raw.getvalue())
        for blob in self.business.storage.blobs.iterdir():
            self.assertNotIn(raw.getvalue(), blob.read_bytes())

    def test_multipart_is_memory_only_and_duplicates_are_reused(self):
        with patch('starlette.requests.Request.form', side_effect=AssertionError('No automatic form spooling')), \
             patch('starlette.formparsers.SpooledTemporaryFile', side_effect=AssertionError('No plaintext temporary upload')), \
             patch('tempfile.SpooledTemporaryFile', side_effect=AssertionError('No plaintext temporary upload')):
            response = self.upload(count=2)
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        uuid.UUID(body['batch_id'])
        self.assertEqual(len(body['task_ids']), 1)
        task = self.task(body['task_ids'][0])
        self.assert_task_contract(task)
        self.assertEqual(task['status'], 'QUEUED')
        self.assertIn('DUPLICATE_FILE', [warning['code'] for warning in task['warnings']])
        listing = self.client.get('/api/v1/tasks?page=1&page_size=1', headers=self.headers).json()
        self.assertEqual((listing['total'], listing['page'], listing['page_size']), (1, 1, 1))
        self.assert_task_contract(listing['items'][0])

    def test_invalid_decode_and_incomplete_multipart_are_atomic(self):
        self.assertEqual(self.assert_error(self.upload(data=b'PRIVATE_BAD_IMAGE'), 422)['code'], 'DECODE_FAILED')
        response = self.client.post('/api/v1/batches', headers={**self.headers,
                                    'Content-Type': 'multipart/form-data; boundary=unfinished'},
                                    content=b'--unfinished\r\nContent-Disposition: form-data; name="files"; filename="a.png"\r\n\r\nprivate')
        self.assert_error(response, 400)
        self.assertEqual(self.business.store.tasks(), [])
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_version_checks_cancel_rerun_and_result_contract(self):
        created = self.upload().json()
        task_id = created['task_ids'][0]
        initial = self.task(task_id)
        version = dict(run_id=initial['run_id'], expected_revision=initial['result_revision'])
        response = self.client.post(f'/api/v1/tasks/{task_id}/cancel', headers=self.headers, json=version)
        self.assertEqual(response.status_code, 202, response.text)
        cancelled = response.json()
        self.assert_task_contract(cancelled)
        self.assertEqual(cancelled['status'], 'CANCELLED')
        stale = self.client.post(f'/api/v1/tasks/{task_id}/rerun', headers=self.headers, json=version)
        self.assertEqual(self.assert_error(stale, 409)['code'], 'RESULT_VERSION_CONFLICT')
        fresh = self.client.post(f'/api/v1/tasks/{task_id}/rerun', headers=self.headers,
                                 json=dict(run_id=cancelled['run_id'], expected_revision=cancelled['result_revision']))
        self.assertEqual(fresh.status_code, 202, fresh.text)
        self.assertNotEqual(fresh.json()['run_id'], initial['run_id'])
        claimed = self.business.store.claim_next()
        self.business.store.publish(claimed, dict(doc_type='DIPLOMA', status='NEED_REVIEW', review_issues=[],
                                                  fields=[], pages=[], warnings=[]))
        result = self.client.get(f'/api/v1/tasks/{task_id}/result', headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertTrue({'task_id', 'doc_type', 'run_id', 'result_revision', 'status', 'review_issues'} <= payload.keys())
        self.assertEqual(payload['run_id'], fresh.json()['run_id'])
        self.assertGreater(payload['result_revision'], fresh.json()['result_revision'])

    def test_request_validation_does_not_echo_submitted_sensitive_values(self):
        secret = 'PRIVATE_6222021234567890123'
        response = self.client.post('/api/v1/tasks/' + str(uuid.uuid4()) + '/cancel', headers=self.headers,
                                    json=dict(run_id=secret, expected_revision=-1))
        self.assert_error(response, 422)
        self.assertNotIn(secret, response.text)

    def test_unavailable_runtime_rejects_upload_before_persistence(self):
        self.runtime.alive = False
        self.assert_error(self.upload(), 503)
        self.assertEqual(self.business.store.tasks(), [])
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_medical_filter_changes_items_only_and_all_overrides_option(self):
        created = self.upload('MEDICAL_REPORT', abnormal_only=True).json()
        task_id = created['task_ids'][0]
        claimed = self.business.store.claim_next()
        items = [dict(item_id=str(uuid.uuid4()), name=name, result_raw='synthetic', abnormal_flag=flag,
                      reported_abnormal_marker='↑' if flag == 'HIGH' else None, abnormal_basis=basis, confidence=None,
                      confidence_method='unavailable', need_review=True, review_issues=[])
                 for name, flag, basis in [('normal', 'NORMAL', 'reference_comparison'), ('high', 'HIGH', 'report_marker'),
                                          ('unknown', 'UNKNOWN', 'unknown'), ('positive', 'POSITIVE', 'unknown')]]
        stats = dict(total=4, normal=1, abnormal=1, unknown=2, categories={})
        self.business.store.publish(claimed, dict(doc_type='MEDICAL_REPORT', status='NEED_REVIEW',
            review_issues=[], pages=[], basic_info={}, items=items, stats=stats, abnormal_summary=[items[1]],
            normal_summary='synthetic normal summary', warnings=[]))
        path = f'/api/v1/tasks/{task_id}/result'
        variants = [('', {'high', 'unknown', 'positive'}), ('?items_filter=all', {'normal', 'high', 'unknown', 'positive'}),
                    ('?items_filter=abnormal', {'high'}), ('?items_filter=unknown', {'unknown', 'positive'})]
        for suffix, expected in variants:
            with self.subTest(filter=suffix):
                response = self.client.get(path + suffix, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual({item['name'] for item in body['items']}, expected)
                self.assertEqual(body['stats'], stats)
                self.assertEqual(body['abnormal_summary'], [items[1]])
                self.assertTrue({'basic_info', 'items', 'stats', 'abnormal_summary', 'review_issues'} <= body.keys())
        self.assert_error(self.client.get(path + '?items_filter=PRIVATE_BAD_VALUE', headers=self.headers), 422)
        for include in ('true', 'false'):
            with self.subTest(include_normal_summary=include):
                body = self.client.get(path + '?items_filter=all&include_normal_summary=' + include,
                                       headers=self.headers).json()
                self.assertEqual(body['normal_summary'], 'synthetic normal summary' if include == 'true' else None)
                self.assertEqual(len(body['items']), 4)
                self.assertEqual(body['stats'], stats)


if __name__ == '__main__':
    unittest.main()
