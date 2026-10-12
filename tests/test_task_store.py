"""Durable task tests: real temporary SQLite/encrypted blobs, no OCR process."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import itertools
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.db import open_database
from ocr_app.storage import Storage
from ocr_app.task_store import ACTIVE, TaskError, TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'data'
        self.storage = Storage(self.root, key=b'K' * 32)
        self.engine = open_database(self.root)
        self.addCleanup(self.engine.dispose)
        self.store = TaskStore(self.engine, self.storage)

    def create(self, data=b'synthetic document', name='synthetic.png', options=None, page_count=None):
        value = self.store.create_batch([dict(data=data, name=name, mime='image/png', actual_source_page_count=page_count)],
                                        'DIPLOMA', 'test-operator', options)
        return self.store.task(value['task_ids'][0])

    def result(self, status='COMPLETED', secret='synthetic result'):
        return dict(doc_type='DIPLOMA', status=status, review_issues=[], fields=[], pages=[],
                    raw_text=secret, warnings=[])

    def count(self, table):
        self.assertIn(table, {'tasks', 'batches', 'runs', 'artifacts', 'attempts', 'audit'})
        with self.engine.connect() as connection:
            return connection.exec_driver_sql('SELECT COUNT(*) FROM ' + table).scalar_one()

    def test_same_batch_hash_reuses_task_but_other_batch_is_independent(self):
        files = [dict(data=b'identical', name=name, mime='image/png') for name in ('one.png', 'two.png')]
        first = self.store.create_batch(files, 'DIPLOMA', 'operator')
        self.assertEqual(len(first['task_ids']), 1)
        self.assertEqual(self.count('tasks'), 1)
        self.assertEqual(len(list(self.storage.blobs.iterdir())), 1)
        task = self.store.task(first['task_ids'][0])
        self.assertIn('DUPLICATE_FILE', [row['code'] for row in task['warnings']])
        second = self.store.create_batch(files[:1], 'DIPLOMA', 'operator')
        self.assertNotEqual(second['task_ids'], first['task_ids'])
        self.assertEqual(self.count('tasks'), 2)

    def test_numeric_uuid_and_complete_business_values_are_preserved(self):
        serial = itertools.count(1)
        with patch('ocr_app.task_store.identity', side_effect=lambda: str(uuid.UUID(int=next(serial)))):
            task = self.create(data=b'identity-only')
        uuid.UUID(task['task_id'])
        uuid.UUID(task['run_id'])
        uuid.UUID(task['batch_id'])
        self.assertNotIn('*', task['content_hash'])
        claimed = self.store.claim_next()
        item_id = str(uuid.UUID(int=300))
        value = self.result()
        value['fields'] = [dict(key='id_number', value='6222021234567890123', source={'page_id': item_id})]
        value['error'] = dict(code='INTERNAL_ERROR', message='Controlled failure', error_id='e_' + '1' * 32)
        self.store.publish(claimed, value)
        result = self.store.result(task['task_id'])
        self.assertEqual(result['task_id'], task['task_id'])
        self.assertEqual(result['run_id'], task['run_id'])
        self.assertEqual(result['fields'][0]['source']['page_id'], item_id)
        self.assertEqual(result['error']['error_id'], 'e_' + '1' * 32)
        self.assertEqual(result['fields'][0]['value'], '6222021234567890123')

    def test_partial_file_failure_rolls_back_batch_tasks_and_blobs(self):
        original = self.storage.put
        calls = []
        def fail_second(data):
            calls.append(data)
            if len(calls) == 2:
                raise OSError('simulated disk write failure')
            return original(data)
        files = [dict(data=data, name='synthetic.png', mime='image/png') for data in (b'one', b'two')]
        with patch.object(self.storage, 'put', side_effect=fail_second), self.assertRaises(OSError):
            self.store.create_batch(files, 'DIPLOMA', 'operator')
        for table in ('batches', 'tasks', 'runs', 'artifacts', 'audit'):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(list(self.storage.blobs.iterdir()), [])

    def test_commit_failure_leaves_no_accepted_task_or_orphan_blob(self):
        def fail_commit(connection):
            raise OSError('simulated commit failure')
        event.listen(self.engine, 'commit', fail_commit)
        try:
            with self.assertRaises(OSError):
                self.create()
        finally:
            event.remove(self.engine, 'commit', fail_commit)
        for table in ('batches', 'tasks', 'runs', 'artifacts'):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(list(self.storage.blobs.iterdir()), [])

    def test_concurrent_claim_has_only_one_owner(self):
        task = self.create()
        barrier = threading.Barrier(2)
        def claim():
            barrier.wait(timeout=3)
            return self.store.claim_next()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        claimed = [row for row in results if row is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]['id'], task['task_id'])
        self.assertEqual(self.store.task(task['task_id'])['status'], 'PREPROCESSING')

    def test_progress_counts_require_a_complete_plan_and_exclude_native_text(self):
        task = self.create(page_count=2)
        self.assertEqual(self.store.task(task['task_id'])['progress_detail'], dict(
            stage='QUEUED', prepared_pages=0, total_pages=2, processed_regions=0,
            recognized_regions=0, incomplete_regions=0, total_regions=None))
        claimed = self.store.claim_next()
        pages = [dict(page_index=1, _preparation_complete=True, regions=[
            dict(extraction_method='ocr', status='pending'),
            dict(extraction_method='pdf_text', status='recognized')])]
        self.store.progress(claimed, 'PREPROCESSING', 0, pages)
        detail = self.store.task(task['task_id'])['progress_detail']
        self.assertEqual((detail['prepared_pages'], detail['total_regions']), (1, None))
        pages.append(dict(page_index=2, regions=[dict(extraction_method='ocr', status='pending')]))
        self.store.progress(claimed, 'PREPROCESSING', 0, pages)
        self.assertIsNone(self.store.task(task['task_id'])['progress_detail']['total_regions'])
        pages[1]['_preparation_complete'] = True
        pages[0]['regions'][0]['status'] = 'recognized'
        pages[1]['regions'][0]['status'] = 'incomplete'
        self.store.progress(claimed, 'OCR', 99, pages)
        public = self.store.task(task['task_id'])
        self.assertEqual(public['progress_detail'], dict(stage='OCR', prepared_pages=2,
            total_pages=2, processed_regions=2, recognized_regions=1, incomplete_regions=1, total_regions=2))
        self.assertNotIn('_preparation_complete', json.dumps(public))
        self.assertEqual(self.store.tasks(task['batch_id'])[0]['progress_detail'], public['progress_detail'])

    def test_legacy_and_unknown_source_pages_do_not_invent_an_ocr_total(self):
        for page_count, marker in [(None, True), (1, False)]:
            with self.subTest(page_count=page_count, marker=marker):
                task = self.create(data=str((page_count, marker)).encode(), page_count=page_count)
                claimed = self.store.claim_next()
                pages = [dict(page_index=1, regions=[dict(extraction_method='ocr', status='recognized')])]
                if marker:
                    pages[0]['_preparation_complete'] = True
                self.store.progress(claimed, 'OCR', 99, pages)
                detail = self.store.task(task['task_id'])['progress_detail']
                self.assertIsNone(detail['total_regions'])
                self.assertEqual(detail['processed_regions'], 1)
                self.store.publish(claimed, dict(self.result(), pages=pages))

    def test_failed_or_cancelled_publication_does_not_manufacture_full_progress(self):
        for cancel in [False, True]:
            with self.subTest(cancel=cancel):
                task = self.create(data=str(cancel).encode(), page_count=1)
                claimed = self.store.claim_next()
                pages = [dict(page_index=1, _preparation_complete=True, regions=[
                    dict(extraction_method='ocr', status='recognized'),
                    dict(extraction_method='ocr', status='pending')])]
                self.store.progress(claimed, 'OCR', 50, pages)
                if cancel:
                    self.store.cancel(task['task_id'], task['run_id'], task['result_revision'], 'operator')
                self.store.publish(claimed, dict(self.result('FAILED'), pages=pages))
                public = self.store.task(task['task_id'])
                self.assertEqual(public['status'], 'CANCELLED' if cancel else 'FAILED')
                self.assertEqual(public['progress'], 50)
                self.assertEqual(public['progress_detail']['processed_regions'], 1)
                self.assertEqual(public['progress_detail']['total_regions'], 2)
                rerun = self.store.rerun(public['task_id'], public['run_id'], public['result_revision'], 'operator')
                self.assertEqual(rerun['progress'], 0)
                self.assertEqual(rerun['progress_detail']['processed_regions'], 0)
                self.assertIsNone(rerun['progress_detail']['total_regions'])
                self.assertFalse(self.store.progress(claimed, 'OCR', 99, pages))
                self.assertEqual(self.store.task(task['task_id'])['progress_detail'], rerun['progress_detail'])
                self.store.cancel(rerun['task_id'], rerun['run_id'], rerun['result_revision'], 'operator')

    def test_cancel_queued_prevents_claim_and_stale_revision_is_rejected(self):
        task = self.create()
        cancelled = self.store.cancel(task['task_id'], task['run_id'], task['result_revision'], 'operator')
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertTrue(cancelled['cancel_requested'])
        self.assertIsNone(self.store.claim_next())
        with self.assertRaises(TaskError) as caught:
            self.store.rerun(task['task_id'], task['run_id'], task['result_revision'], 'operator')
        self.assertEqual(caught.exception.code, 'RESULT_VERSION_CONFLICT')

    def test_cancel_active_wins_over_late_completion(self):
        task = self.create()
        claimed = self.store.claim_next()
        cancelled = self.store.cancel(task['task_id'], task['run_id'], task['result_revision'], 'operator')
        self.assertIn(cancelled['status'], ACTIVE)
        self.assertTrue(cancelled['cancel_requested'])
        self.assertFalse(self.store.progress(claimed, 'OCR', 40))
        self.store.publish(claimed, self.result(secret='MUST_NOT_PUBLISH_CANCELLED_RESULT'))
        self.assertEqual(self.store.task(task['task_id'])['status'], 'CANCELLED')
        try:
            result = self.store.result(task['task_id'])
        except TaskError:
            return
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertNotIn('MUST_NOT_PUBLISH_CANCELLED_RESULT', json.dumps(result))

    def test_completion_wins_then_cancel_rejects_old_version(self):
        task = self.create()
        claimed = self.store.claim_next()
        self.assertTrue(self.store.publish(claimed, self.result()))
        with self.assertRaises(TaskError) as caught:
            self.store.cancel(task['task_id'], task['run_id'], task['result_revision'], 'operator')
        self.assertEqual(caught.exception.code, 'RESULT_VERSION_CONFLICT')
        self.assertEqual(self.store.task(task['task_id'])['status'], 'COMPLETED')

    def test_concurrent_cancel_and_completion_have_one_consistent_winner(self):
        task = self.create()
        claimed = self.store.claim_next()
        barrier = threading.Barrier(2)
        def cancel():
            barrier.wait(timeout=3)
            try:
                return self.store.cancel(task['task_id'], task['run_id'], task['result_revision'], 'operator')
            except TaskError as error:
                return error.code
        def complete():
            barrier.wait(timeout=3)
            return self.store.publish(claimed, self.result(secret='LATE_RESULT'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation, completion = pool.submit(cancel), pool.submit(complete)
            cancel_result, publish_result = cancellation.result(timeout=5), completion.result(timeout=5)
        current = self.store.task(task['task_id'])
        self.assertTrue(publish_result)
        self.assertIn(current['status'], {'COMPLETED', 'CANCELLED'})
        if current['status'] == 'COMPLETED':
            self.assertEqual(cancel_result, 'RESULT_VERSION_CONFLICT')
            self.assertFalse(current['cancel_requested'])
            self.assertEqual(self.store.result(task['task_id'])['status'], 'COMPLETED')
        else:
            self.assertTrue(current['cancel_requested'])
            try:
                result = self.store.result(task['task_id'])
            except TaskError:
                return
            self.assertEqual(result['status'], 'CANCELLED')
            self.assertNotIn('LATE_RESULT', json.dumps(result))

    def test_rerun_does_not_carry_previous_execution_warnings(self):
        task = self.create()
        claimed = self.store.claim_next()
        old_result = self.result()
        old_result['warnings'] = [dict(code='PDF_TEXT_UNRELIABLE', message='old execution warning')]
        self.store.publish(claimed, old_result)
        current = self.store.task(task['task_id'])
        self.assertEqual(current['warnings'][0]['code'], 'PDF_TEXT_UNRELIABLE')
        self.store.rerun(task['task_id'], current['run_id'], current['result_revision'], 'operator')
        self.store.publish(self.store.claim_next(), self.result())
        self.assertNotIn('PDF_TEXT_UNRELIABLE', [item['code'] for item in self.store.task(task['task_id'])['warnings']])

    def test_rerun_keeps_history_and_old_worker_cannot_publish(self):
        task = self.create()
        original = self.store.claim_next()
        self.store.attempt(original, {'text': 'old-private-output'})
        self.store.publish(original, self.result(secret='old-private-output'))
        completed = self.store.task(task['task_id'])
        rerun = self.store.rerun(task['task_id'], completed['run_id'], completed['result_revision'], 'operator')
        self.assertNotEqual(rerun['run_id'], completed['run_id'])
        self.assertGreater(rerun['result_revision'], completed['result_revision'])
        current = self.store.claim_next()
        self.assertFalse(self.store.publish(original, self.result(secret='stale-private-output')))
        self.assertTrue(self.store.publish(current, self.result(secret='new-private-output')))
        self.assertEqual(self.store.result(task['task_id'])['raw_text'], 'new-private-output')
        with self.engine.connect() as connection:
            history = connection.execute(text('SELECT result_enc FROM runs WHERE id=:id'), {'id': original['run_id']}).scalar_one()
        self.assertEqual(self.storage.unpack(history)['raw_text'], 'old-private-output')
        self.assertEqual(self.count('runs'), 2)
        self.assertEqual(self.count('attempts'), 1)

    def test_terminal_run_cannot_add_pages(self):
        task = self.create()
        claimed = self.store.claim_next()
        self.store.publish(claimed, self.result())
        before = set(self.storage.blobs.iterdir())
        with self.assertRaises(TaskError):
            self.store.save_page(claimed, 0, b'late image', 100, 100)
        self.assertEqual(set(self.storage.blobs.iterdir()), before)

    def test_recover_marks_only_interrupted_active_tasks(self):
        active_ids = []
        for index, stage in enumerate(sorted(ACTIVE)):
            task = self.create(data=f'active-{index}'.encode())
            claimed = self.store.claim_next()
            self.store.progress(claimed, stage, 30)
            active_ids.append(task['task_id'])
        completed = self.create(data=b'complete')
        self.store.publish(self.store.claim_next(), self.result())
        queued = self.create(data=b'queued')
        before_completed = self.store.task(completed['task_id'])
        self.store.recover()
        for task_id in active_ids:
            task = self.store.task(task_id)
            self.assertEqual(task['status'], 'FAILED')
            self.assertEqual(task['error']['code'], 'WORKER_INTERRUPTED')
        self.assertEqual(self.store.task(queued['task_id'])['status'], 'QUEUED')
        self.assertEqual(self.store.task(completed['task_id']), before_completed)

    def test_seven_day_cleanup_includes_run_history_and_owned_artifacts(self):
        task = self.create()
        for index in range(2):
            claimed = self.store.claim_next()
            self.store.save_page(claimed, index, b'private-page-' + bytes([index]), 10, 10)
            self.store.attempt(claimed, {'text': 'private-history'})
            self.store.publish(claimed, self.result())
            if index == 0:
                current = self.store.task(task['task_id'])
                self.store.rerun(task['task_id'], current['run_id'], current['result_revision'], 'operator')
        self.assertEqual(self.count('runs'), 2)
        self.assertEqual(self.count('attempts'), 2)
        self.store.cleanup(at=(datetime.now(timezone.utc) + timedelta(days=6)).isoformat())
        self.assertEqual(self.count('tasks'), 1)
        self.store.cleanup(at=(datetime.now(timezone.utc) + timedelta(days=8)).isoformat())
        for table in ('tasks', 'batches', 'runs', 'attempts', 'artifacts'):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(list(self.storage.blobs.iterdir()), [])
        self.assertGreater(self.count('audit'), 0)

    def test_cleanup_never_deletes_an_active_worker_input(self):
        task = self.create()
        claimed = self.store.claim_next()
        self.store.cleanup(at=(datetime.now(timezone.utc) + timedelta(days=8)).isoformat())
        self.assertEqual(self.store.task(task['task_id'])['status'], 'PREPROCESSING')
        self.assertEqual(self.storage.read(claimed['input_ref']), b'synthetic document')

    def test_sensitive_bytes_do_not_appear_on_disk(self):
        secret = 'PRIVATE_DOCUMENT_6222021234567890123'
        task = self.create(data=secret.encode(), name=secret + '.png')
        claimed = self.store.claim_next()
        self.store.attempt(claimed, {'text': secret})
        self.store.save_page(claimed, 0, secret.encode(), 20, 20)
        self.store.publish(claimed, self.result(secret=secret))
        self.assertEqual(self.storage.read(claimed['input_ref']), secret.encode())
        self.assertEqual(self.store.result(task['task_id'])['raw_text'], secret)
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), path.name)

    def test_medical_filters_preserve_independent_encrypted_summary(self):
        task = self.create()
        claimed = self.store.claim_next()
        secret = 'SYNTHETIC_REPORT_SUMMARY_6222021234567890123'
        summary = dict(scope='follow_up_required', declared_count=1, count_check='match',
                       sources=[dict(raw_text=secret)], findings=[dict(finding_id=str(uuid.uuid4()),
                       reported_number='1', text=secret, sources=[])])
        value = self.result()
        value.update(doc_type='MEDICAL_REPORT', report_summary=summary, items=[
            dict(abnormal_flag='HIGH', abnormal_basis='report_marker'),
            dict(abnormal_flag='NORMAL', abnormal_basis='reference_comparison'),
            dict(abnormal_flag='UNKNOWN', abnormal_basis='unknown'),
            dict(abnormal_flag='POSITIVE', abnormal_basis='unknown'),
            dict(abnormal_flag='POSITIVE', abnormal_basis='report_marker')])
        self.store.publish(claimed, value)
        all_result = self.store.result(task['task_id'], 'all')
        for selected, expected in [('all', 5), ('flagged', 4), ('abnormal', 2), ('unknown', 2)]:
            filtered = self.store.result(task['task_id'], selected, include_normal_summary=False)
            self.assertEqual(filtered['report_summary'], all_result['report_summary'])
            self.assertEqual(len(filtered['items']), expected)
        self.assertEqual(all_result['report_summary'], summary)
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), path.name)


if __name__ == '__main__':
    unittest.main()
