"""CPU-only regressions for shutdown confirmation, watchdog ordering and DPAPI."""
from datetime import datetime, timezone
import io
import os
import queue
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.business import Business
from ocr_app.client import RuntimeClient
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import RuntimeFailure
from ocr_app.storage import Storage, _dpapi
from sqlalchemy import text


class ControlledProcess:
    pid = 12345

    def __init__(self, failure=False):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.exited = False
        self.failure = failure
        self.close_calls = 0
        self.stdin = io.StringIO()

    def poll(self):
        return 0 if self.exited else None

    def close(self):
        self.close_calls += 1
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError('Test failed to release controlled close')
        if self.failure:
            raise OSError('Synthetic supervision failure')
        self.exited = True


class TwoTicks:
    def __init__(self):
        self.count = 0

    def wait(self, timeout):
        self.count += 1
        return self.count > 2

    def set(self):
        self.count = 3


class BusinessWatchdogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def client(self, failure=False):
        client = RuntimeClient(RuntimeConfig(self.root / 'session'))
        client.process = ControlledProcess(failure)
        return client

    def business(self):
        business = Business.__new__(Business)
        business.logger = Mock()
        business.stop_event = TwoTicks()
        business.monitor = None
        business.store = Mock()
        business.engine = Mock()
        business.store.active.return_value = [dict(id='task', run_id='run',
            active_started_at=datetime.now(timezone.utc).isoformat())]
        return business

    def real_business(self, logger=None):
        business = Business(self.root / 'data', logger=logger, key=b'W' * 32)
        self.addCleanup(business.close)
        batch = business.store.create_batch([dict(data=b'synthetic', name='test.png', mime='image/png')],
                                           'DIPLOMA', 'test-operator')
        return business, batch['task_ids'][0]

    @staticmethod
    def result():
        return dict(status='COMPLETED', doc_type='DIPLOMA', pages=[], fields=[], review_issues=[], warnings=[])

    def test_parallel_close_cannot_return_before_process_exit(self):
        client = self.client()
        finished, failures = threading.Event(), []
        def close(mark=False):
            try:
                client.close(graceful=False)
                if mark:
                    finished.set()
            except BaseException as error:
                failures.append(error)
        first = threading.Thread(target=close)
        second = threading.Thread(target=lambda: close(True))
        first.start()
        self.assertTrue(client.process.entered.wait(1))
        second.start()
        try:
            self.assertFalse(finished.wait(.1), 'closing flag is not termination confirmation')
        finally:
            client.process.release.set()
            first.join(3)
            second.join(3)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(finished.is_set())
        self.assertTrue(client.process.exited)
        self.assertEqual(client.process.close_calls, 1)

    def test_failed_close_is_not_silently_successful_on_next_call(self):
        client = self.client(failure=True)
        client.process.release.set()
        with self.assertRaises(Exception):
            client.close(graceful=False)
        with self.assertRaises(RuntimeFailure) as caught:
            client.close(graceful=False)
        self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
        self.assertFalse(client.process.exited)

    def test_shutdown_timeout_does_not_wait_for_its_own_close(self):
        client = self.client()
        client.process.release.set()
        with patch('ocr_app.client.queue.Queue.get', side_effect=queue.Empty), \
                patch.object(client._close_done, 'wait', side_effect=AssertionError('Owner must not await itself')):
            client.close()
        self.assertTrue(client.is_stopped())
        self.assertEqual(client.process.close_calls, 1)

    def test_parallel_close_has_bounded_shared_confirmation_wait(self):
        client = self.client()
        failures = []
        def owner_close():
            try:
                client.close(graceful=False)
            except BaseException as error:
                failures.append(error)
        with patch('ocr_app.client.CLOSE_WAIT_SECONDS', .05):
            owner = threading.Thread(target=owner_close)
            owner.start()
            self.assertTrue(client.process.entered.wait(1))
            try:
                with self.assertRaises(RuntimeFailure) as caught:
                    client.close(graceful=False)
                self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
                self.assertFalse(client.is_stopped())
            finally:
                client.process.release.set()
                owner.join(3)
        self.assertEqual(failures, [])
        self.assertTrue(client.is_stopped())

    def test_watchdog_does_not_recover_when_shutdown_failed(self):
        client = self.client(failure=True)
        client.process.release.set()
        try:
            client.close(graceful=False)
        except Exception:
            pass
        business = self.business()
        business.watch(client)
        business.monitor.join(2)
        self.assertFalse(business.monitor.is_alive())
        business.store.recover.assert_not_called()
        business.logger.exception.assert_called()

    def test_watchdog_recovers_only_after_parallel_shutdown_finishes(self):
        client = self.client()
        failures = []
        def close():
            try:
                client.close(graceful=False)
            except BaseException as error:
                failures.append(error)
        owner = threading.Thread(target=close)
        owner.start()
        self.assertTrue(client.process.entered.wait(1))
        business = self.business()
        recovered = threading.Event()
        def recover(*args, **kwargs):
            self.assertTrue(client.process.exited)
            recovered.set()
        business.store.recover.side_effect = recover
        business.watch(client)
        try:
            self.assertFalse(recovered.wait(.1))
        finally:
            client.process.release.set()
            owner.join(3)
            business.monitor.join(3)
        self.assertEqual(failures, [])
        self.assertTrue(recovered.is_set())

    def test_obsolete_run_timeout_does_not_stop_new_execution(self):
        business, task_id = self.real_business()
        old = business.store.claim_next()
        old = business.store.active()[0]
        business.store.publish(old, self.result())
        task = business.store.task(task_id)
        business.store.rerun(task_id, task['run_id'], task['result_revision'], 'operator')
        current = business.store.claim_next()
        stop = Mock()
        self.assertFalse(business.store.timeout_run(old, 0, stop))
        stop.assert_not_called()
        self.assertEqual(business.store.task(task_id)['run_id'], current['run_id'])
        self.assertEqual(business.store.task(task_id)['status'], 'PREPROCESSING')

    def test_start_marker_and_monotonic_deadline_are_rechecked_under_lock(self):
        business, task_id = self.real_business()
        task = business.store.claim_next()
        task = business.store.active()[0]
        stop = Mock()
        self.assertFalse(business.store.timeout_run(task, time.monotonic() + 100, stop))
        with business.store.transaction() as connection:
            connection.execute(text('UPDATE tasks SET active_started_at=:at WHERE id=:id'),
                               dict(id=task_id, at='changed-start-marker'))
        self.assertFalse(business.store.timeout_run(task, 0, stop))
        stop.assert_not_called()

    def test_timeout_fences_target_without_holding_writer_lock_during_stop(self):
        business, task_id = self.real_business()
        task = business.store.claim_next()
        task = business.store.active()[0]
        business.store.create_batch([dict(data=b'other', name='other.png', mime='image/png')],
                                    'MEDICAL_REPORT', 'test-operator')
        other = business.store.claim_next()
        entered, release, publish_started, published = (threading.Event() for _ in range(4))
        failures, outputs = [], {}
        def stop():
            self.assertEqual(business.store.task(task_id)['status'], 'PREPROCESSING')
            entered.set()
            if not release.wait(2):
                raise TimeoutError('Test failed to release stop')
            return True
        def timeout():
            try:
                outputs['timeout'] = business.store.timeout_run(task, 0, stop)
            except BaseException as error:
                failures.append(error)
        def publish():
            publish_started.set()
            try:
                outputs['publish'] = business.store.publish(task, self.result())
                outputs['other_publish'] = business.store.publish(other, self.result())
            except BaseException as error:
                failures.append(error)
            finally:
                published.set()
        timeout_thread = threading.Thread(target=timeout)
        publisher = threading.Thread(target=publish)
        timeout_thread.start()
        try:
            self.assertTrue(entered.wait(1))
            publisher.start()
            self.assertTrue(publish_started.wait(1))
            self.assertTrue(published.wait(1), 'unrelated publication must not wait for stop confirmation')
            self.assertEqual(business.store.task(task_id)['status'], 'PREPROCESSING')
        finally:
            release.set()
            timeout_thread.join(3)
            if publisher.ident is not None:
                publisher.join(3)
        self.assertEqual(failures, [])
        self.assertEqual(outputs, {'timeout': True, 'publish': False, 'other_publish': True})
        current = business.store.task(task_id)
        self.assertEqual(current['status'], 'FAILED')
        self.assertEqual(current['error']['code'], 'EXTRACT_TIMEOUT')

    def test_stop_failure_does_not_recover_or_increment_revision(self):
        business, task_id = self.real_business()
        task = business.store.claim_next()
        task = business.store.active()[0]
        with self.assertRaises(RuntimeFailure):
            business.store.timeout_run(task, 0, Mock(side_effect=RuntimeFailure('SUPERVISION_FAILED')))
        current = business.store.task(task_id)
        self.assertEqual(current['status'], 'PREPROCESSING')
        self.assertEqual(current['result_revision'], task['revision'])
        self.assertIsNone(current['error'])

    def test_watchdog_uses_first_seen_monotonic_not_wall_clock(self):
        for wall_start in ('1900-01-01T00:00:00+00:00', '2999-01-01T00:00:00+00:00'):
            with self.subTest(wall_start=wall_start):
                business = self.business()
                business.store.active.return_value[0]['active_started_at'] = wall_start
                runtime = Mock()
                runtime.is_alive.return_value = True
                business.store.timeout_run.side_effect = lambda task, deadline, stop: (stop(), True)[1]
                with patch('ocr_app.business.monotonic', side_effect=[10., 192.], create=True):
                    business.watch(runtime)
                    business.monitor.join(1)
                business.store.timeout_run.assert_called_once()
                self.assertEqual(business.store.timeout_run.call_args.args[1], 191.)
                runtime.stop_task.assert_called_once_with(business.store.active.return_value[0])
                runtime.close.assert_not_called()

    def test_stop_task_requires_exact_run_confirmation_and_bounded_control_request(self):
        client = self.client()
        task = dict(id='task', run_id='run')
        with patch.object(client, 'request', return_value=dict(stopped=True, task_id='task', run_id='run')) as request:
            self.assertTrue(client.stop_task(task))
            request.assert_called_once_with('stop_task', wait=20.0, task_id='task', run_id='run')
        for response in [dict(stopped=True, task_id='task', run_id='old'), dict(stopped=False), {}, True]:
            with self.subTest(response=response), patch.object(client, 'request', return_value=response):
                self.assertFalse(client.stop_task(task))

    def test_control_request_can_complete_while_another_request_is_pending(self):
        client = self.client()
        client.view['state'] = 'ready'
        client.requests[991] = queue.Queue()
        original = client.process.stdin.write
        def write(line):
            import json
            message = json.loads(line)
            original(line)
            client.requests[message['id']].put(dict(ok=True, result=dict(stopped=True, task_id='task', run_id='run')))
        client.process.stdin.write = write
        self.assertTrue(client.stop_task(dict(id='task', run_id='run')))
        self.assertIn(991, client.requests)
        self.assertEqual(client.process.close_calls, 0)

    def test_target_stop_rpc_timeout_still_confirms_global_cleanup(self):
        client = self.client()
        client.view['state'] = 'ready'
        client.process.release.set()
        with patch('ocr_app.client.queue.Queue.get', side_effect=queue.Empty):
            with self.assertRaises(RuntimeFailure) as caught:
                client.stop_task(dict(id='task', run_id='run'))
        self.assertEqual(caught.exception.code, 'MODEL_REQUEST_TIMEOUT')
        self.assertTrue(client.is_stopped())

    def test_watchdog_targets_one_lane_without_closing_healthy_runtime(self):
        business = self.business()
        old = dict(id='old-task', run_id='old-run', active_started_at='start-old')
        other = dict(id='other-task', run_id='other-run', active_started_at='start-other')
        business.store.active.side_effect = [[old], [old, other]]
        runtime = Mock()
        runtime.is_alive.return_value = True
        runtime.stop_task.return_value = True
        business.store.timeout_run.side_effect = lambda task, deadline, stop: stop()
        with patch('ocr_app.business.monotonic', side_effect=[10., 192.]):
            business.watch(runtime)
            business.monitor.join(1)
        runtime.stop_task.assert_called_once_with(old)
        runtime.close.assert_not_called()
        business.store.recover.assert_not_called()

    def test_target_supervision_failure_closes_runtime_without_premature_recovery(self):
        business = self.business()
        runtime = Mock()
        runtime.is_alive.return_value = True
        business.store.timeout_run.side_effect = RuntimeFailure('SUPERVISION_FAILED')
        with patch('ocr_app.business.monotonic', side_effect=[10., 192.]):
            business.watch(runtime)
            business.monitor.join(1)
        runtime.close.assert_called_once_with(graceful=False)
        business.store.recover.assert_not_called()

    def test_new_run_gets_a_new_monotonic_observation_budget(self):
        business = self.business()
        old = dict(id='task', run_id='old', active_started_at='1900-01-01T00:00:00+00:00')
        new = dict(old, run_id='new')
        business.store.active.side_effect = [[old], [new]]
        runtime = Mock()
        runtime.is_alive.return_value = True
        with patch('ocr_app.business.monotonic', side_effect=[10., 192.], create=True):
            business.watch(runtime)
            business.monitor.join(1)
        business.store.timeout_run.assert_not_called()
        runtime.close.assert_not_called()

    def test_recovered_task_error_links_to_diagnostic_id(self):
        logger = Mock()
        logger.exception.return_value = 'e_' + uuid.uuid4().hex
        business, task_id = self.real_business(logger)
        task = business.store.claim_next()
        business.store.recover()
        error = business.store.task(task_id)['error']
        self.assertEqual(error['error_id'], logger.exception.return_value)
        logger.exception.assert_called_once()
        self.assertEqual(logger.exception.call_args.kwargs['run_id'], task['run_id'])

    @unittest.skipUnless(os.name == 'nt', 'Windows current-user DPAPI')
    def test_dpapi_roundtrip_and_storage_reopen_do_not_replace_key(self):
        plaintext = b'synthetic DPAPI input, not a real secret'
        protected = _dpapi(plaintext)
        self.assertNotEqual(protected, plaintext)
        self.assertEqual(_dpapi(protected, decrypt=True), plaintext)
        storage = Storage(self.root / 'data')
        reference = storage.put(plaintext)
        key_file = self.root / 'secrets/data-key.dpapi'
        key_before = key_file.read_bytes()
        second = Storage(self.root / 'data')
        self.assertEqual(second.read(reference), plaintext)
        self.assertEqual(key_file.read_bytes(), key_before)
        self.assertNotIn(plaintext, storage.path(reference).read_bytes())

    def test_missing_key_with_existing_data_fails_closed(self):
        storage = Storage(self.root / 'data', key=b'K' * 32)
        reference = storage.put(b'synthetic encrypted content')
        with self.assertRaisesRegex(RuntimeError, 'MISSING_DATA_KEY'):
            Storage(self.root / 'data')
        self.assertTrue(storage.path(reference).exists())
        self.assertFalse((self.root / 'secrets/data-key.dpapi').exists())


if __name__ == '__main__':
    unittest.main()
