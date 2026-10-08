"""CPU regressions for lane claims, additive migration and exact-run stop fences."""
import sys
import tempfile
import threading
import time
import unittest
import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.db import open_database
from ocr_app.storage import Storage
from ocr_app.task_store import TaskStore, TaskError
from ocr_app.runtime import RuntimeFailure
from ocr_app.task_scheduler import TaskScheduler
from ocr_app.model_queues import ModelQueues


class ParallelTaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / 'data', key=b'T' * 32)
        self.engine = open_database(self.storage.root)
        self.addCleanup(self.engine.dispose)
        self.store = TaskStore(self.engine, self.storage)

    def create(self, kind='DIPLOMA', value=b'synthetic'):
        return self.store.create_batch([dict(data=value, name='fixture.png', mime='image/png')], kind, 'test')['task_ids'][0]

    def raw(self, task_id):
        with self.engine.connect() as connection:
            return dict(connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().one())

    @staticmethod
    def result():
        return dict(status='NEED_REVIEW', fields=[], pages=[], review_issues=[], warnings=[])

    def test_claim_filters_lane_fifo_and_returns_actual_active_marker(self):
        a = self.create('MEDICAL_REPORT', b'a')
        b = self.create('DIPLOMA', b'b')
        c = self.create('DEGREE_CERT', b'c')
        for i, task_id in enumerate([a, b, c]):
            with self.store.transaction() as connection:
                connection.execute(text('UPDATE tasks SET created_at=:at WHERE id=:id'), {'at': str(i), 'id': task_id})
        cert = self.store.claim_next({'DIPLOMA', 'DEGREE_CERT'})
        self.assertEqual(cert['id'], b)
        self.assertEqual(cert['status'], 'PREPROCESSING')
        self.assertTrue(cert['active_started_at'])
        self.assertEqual(cert['active_started_at'], self.raw(b)['active_started_at'])
        self.assertEqual(self.store.claim_next({'MEDICAL_REPORT'})['id'], a)
        self.assertIsNone(self.store.claim_next({'MEDICAL_REPORT'}))
        self.assertIsNone(self.store.claim_next(set()))
        self.assertEqual(self.store.claim_next()['id'], c)

    def test_concurrent_claims_never_claim_same_task(self):
        expected = {self.create(value=str(i).encode()) for i in range(4)}
        barrier, outputs, errors = threading.Barrier(4), [], []
        def claim():
            try:
                barrier.wait()
                outputs.append(self.store.claim_next({'DIPLOMA'})['id'])
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=claim) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(set(outputs), expected)

    def test_failed_stop_keeps_fence_and_rejects_late_progress_page_and_publish(self):
        task_id = self.create()
        task = self.store.claim_next()
        revision = task['revision']
        for response in [False, None]:
            # Each case uses a fresh run; unconfirmed fences cannot be reused.
            if response is None:
                task_id = self.create(value=b'next')
                task = self.store.claim_next()
                revision = task['revision']
            with self.assertRaises(RuntimeFailure) as caught:
                self.store.timeout_run(task, 0, lambda: response)
            self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
            self.assertEqual(self.raw(task_id)['stop_code'], 'EXTRACT_TIMEOUT')
            self.assertEqual(self.raw(task_id)['revision'], revision)
            self.assertTrue(self.store.cancelled(task_id, task['run_id']))
            self.assertFalse(self.store.progress(task, 'OCR', 20, []))
            before = set(self.storage.blobs.iterdir())
            with self.assertRaises(TaskError): self.store.save_page(task, 1, b'png', 1, 1)
            self.assertEqual(set(self.storage.blobs.iterdir()), before)
            self.assertFalse(self.store.publish(task, self.result()))

    def test_confirmed_stop_preserves_partial_pages_and_clears_fence_only_on_rerun(self):
        task_id = self.create()
        task = self.store.claim_next()
        self.store.progress(task, 'OCR', 20, [dict(page_index=1, page_id='synthetic-page')])
        self.assertTrue(self.store.timeout_run(task, 0, lambda: True))
        current = self.store.task(task_id)
        self.assertEqual(current['status'], 'FAILED')
        self.assertEqual(current['page_count'], 1)
        self.assertEqual(current['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertNotIn('stop_code', current)
        self.store.rerun(task_id, current['run_id'], current['result_revision'], 'operator')
        self.assertIsNone(self.raw(task_id)['stop_code'])
        newer = self.store.claim_next()
        self.assertFalse(self.store.finish_stopped(task))
        self.assertEqual(self.raw(task_id)['run_id'], newer['run_id'])

    def test_stale_start_or_unexpired_task_never_invokes_stop(self):
        task_id = self.create()
        task = self.store.claim_next()
        stop = Mock(return_value=True)
        self.assertFalse(self.store.timeout_run(task, time.monotonic()+30, stop))
        self.assertFalse(self.store.timeout_run(dict(task, active_started_at='stale'), 0, stop))
        self.assertFalse(self.store.timeout_run(dict(task, run_id='stale'), 0, stop))
        stop.assert_not_called()
        self.assertIsNone(self.raw(task_id)['stop_code'])

    def test_request_stop_fences_once_without_publishing_recovery(self):
        task_id = self.create()
        task = self.store.claim_next()
        self.assertTrue(self.store.request_stop(task, deadline=0))
        self.assertFalse(self.store.request_stop(task, deadline=0))
        self.assertEqual(self.store.task(task_id)['status'], 'PREPROCESSING')
        self.assertEqual(self.raw(task_id)['revision'], task['revision'])
        with self.assertRaises(ValueError): self.store.request_stop(task)
        self.assertTrue(self.store.finish_stopped(task))

    def test_untyped_stop_failure_is_supervision_failure_and_keeps_fence(self):
        task_id = self.create()
        task = self.store.claim_next()
        with self.assertRaises(RuntimeFailure) as caught:
            self.store.timeout_run(task, 0, Mock(side_effect=OSError('Synthetic stop transport failure')))
        self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
        self.assertEqual(self.raw(task_id)['stop_code'], 'EXTRACT_TIMEOUT')
        self.assertEqual(self.store.task(task_id)['status'], 'PREPROCESSING')

    def test_coordinator_can_finish_before_timeout_confirmation_returns(self):
        task_id = self.create()
        task = self.store.claim_next()
        def stop():
            self.assertTrue(self.store.finish_stopped(task))
            return True
        self.assertTrue(self.store.timeout_run(task, 0, stop))
        self.assertEqual(self.raw(task_id)['revision'], task['revision'] + 1)

    def test_delayed_confirmation_never_changes_a_new_run(self):
        task_id = self.create()
        task = self.store.claim_next()
        current = []
        def stop():
            self.store.finish_stopped(task)
            public = self.store.task(task_id)
            self.store.rerun(task_id, public['run_id'], public['result_revision'], 'operator')
            current.append(self.store.claim_next())
            return True
        self.assertFalse(self.store.timeout_run(task, 0, stop))
        self.assertEqual(self.raw(task_id)['run_id'], current[0]['run_id'])
        self.assertEqual(self.raw(task_id)['status'], 'PREPROCESSING')
        self.assertIsNone(self.raw(task_id)['stop_code'])

    def test_finish_stopped_uses_current_cancel_flag_and_preserves_timeout_reason(self):
        for cancelled in [True, False]:
            task_id = self.create(value=str(cancelled).encode())
            task = self.store.claim_next()
            if cancelled:
                self.store.cancel(task_id, task['run_id'], task['revision'], 'operator')
            else:
                with self.assertRaises(RuntimeFailure):
                    self.store.timeout_run(task, 0, lambda: False)
            self.assertTrue(self.store.finish_stopped(task))
            result = self.store.task(task_id)
            self.assertEqual(result['status'], 'CANCELLED' if cancelled else 'FAILED')
            if not cancelled: self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')
            self.assertFalse(self.store.finish_stopped(task))
            self.assertFalse(self.store.publish(task, self.result()))

    def test_migration_preserves_existing_encrypted_data_and_adds_nullable_fence(self):
        old_root = self.root / 'old'; old_root.mkdir()
        engine = create_engine('sqlite:///' + str(old_root / 'tasks.sqlite3'))
        config = Config(); config.set_main_option('script_location', str(ROOT / 'backend/migrations'))
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, '0001')
        storage = Storage(old_root, key=b'M' * 32)
        old = TaskStore(engine, storage)
        task_id = old.create_batch([dict(data=b'unchanged', name='fixture.png', mime='image/png')], 'DIPLOMA', 'test')['task_ids'][0]
        with engine.connect() as connection:
            before = dict(connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().one())
        engine.dispose()
        upgraded = open_database(old_root)
        try:
            with upgraded.connect() as connection:
                after = dict(connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().one())
                self.assertEqual(connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), '0002')
            self.assertIsNone(after.pop('stop_code'))
            self.assertEqual(before, after)
            self.assertEqual(storage.read(after['input_ref']), b'unchanged')
        finally:
            upgraded.dispose()

    def scheduler(self, models=None, on_spawn=None):
        class Child:
            def __init__(self, config, task, deadline, revisions, logger):
                self.task, self.deadline = task, deadline
                self.messages, self.sent = queue.Queue(), []
                self.closed = threading.Event()
                if on_spawn:
                    on_spawn(self)
            def send(self, message):
                self.sent.append(message)
            def poll(self):
                return 0 if self.closed.is_set() else None
            def close(self):
                self.closed.set()
        manager = SimpleNamespace(parallel_inference=True, metrics=[])
        scheduler = TaskScheduler(self.store, manager, models or Mock(), None, Mock(), Mock(), factory=Child)
        self.addCleanup(scheduler.close)
        return scheduler

    def test_scheduler_normal_done_only_reclaims_process_and_preserves_published_result(self):
        task_id = self.create()
        scheduler = self.scheduler()
        scheduler.poll()
        job = next(iter(scheduler.jobs.values()))
        self.assertTrue(self.store.publish(job.task, self.result()))
        before = self.raw(task_id)
        job.child.messages.put(dict(event='done', task_id=task_id, run_id=job.task['run_id']))
        scheduler.poll()
        job.stop_thread.join(1)
        scheduler.poll()
        after = self.raw(task_id)
        self.assertEqual(after['status'], 'NEED_REVIEW')
        self.assertEqual(after['result_enc'], before['result_enc'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertIsNone(after['stop_code'])
        self.assertTrue(job.child.closed.is_set())
        self.assertNotIn((task_id, job.task['run_id']), scheduler.jobs)

    def test_scheduler_spawn_time_counts_and_timeout_fence_precedes_queue_stop(self):
        task_id = self.create()
        clock = [100.0]
        def delayed_spawn(child):
            self.assertEqual(child.deadline, 280.0)
            clock[0] = 281.0
        models = Mock()
        def stop_run(stopped_id, run_id):
            self.assertEqual(stopped_id, task_id)
            self.assertEqual(self.raw(task_id)['stop_code'], 'EXTRACT_TIMEOUT')
            self.assertEqual(self.raw(task_id)['status'], 'PREPROCESSING')
        models.stop_run.side_effect = stop_run
        scheduler = self.scheduler(models, delayed_spawn)
        with patch('ocr_app.task_scheduler.time.monotonic', side_effect=lambda: clock[0]), \
                patch('ocr_app.task_store.monotonic', side_effect=lambda: clock[0]):
            scheduler.poll()
            job = next(iter(scheduler.jobs.values()))
            scheduler.poll()
            job.stop_thread.join(1)
            scheduler.poll()
        self.assertEqual(self.store.task(task_id)['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertEqual(self.store.task(task_id)['status'], 'FAILED')
        models.stop_run.assert_called_once_with(task_id, job.task['run_id'])

    def test_scheduler_requests_match_real_model_queue_payload_contract(self):
        self.create()
        manager = SimpleNamespace(recognize=Mock(return_value=dict(text='synthetic', termination_reason='eos')),
                                  stop_run=Mock(), close=Mock())
        models = ModelQueues(manager)
        self.addCleanup(models.close)
        scheduler = self.scheduler(models)
        scheduler.poll()
        job = next(iter(scheduler.jobs.values()))
        scheduler._recognize(job, dict(op='recognize', id=1, model='glm_ocr', task='ocr',
                                       image_base64='eA==', timeout=5.0, max_new_tokens=4096))
        future = job.pending[1]
        self.assertEqual(future.result(timeout=1)['termination_reason'], 'eos')
        scheduler._events()
        self.assertTrue(job.child.sent[0]['ok'])
        self.assertEqual(manager.recognize.call_args.args, ('glm_ocr',))
        self.assertGreater(manager.recognize.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(manager.recognize.call_args.kwargs['timeout'], 5.0)


if __name__ == '__main__':
    unittest.main()
