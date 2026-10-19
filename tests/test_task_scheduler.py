"""CPU-only document-lane routing, responsiveness and owner correlation."""
from concurrent.futures import Future
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.task_scheduler import TaskScheduler
from ocr_app.runtime import RuntimeFailure


def task(name, kind):
    return dict(id=name, run_id=name + '-run', doc_type=kind, active_started_at='2026-10-08', revision=0)


class Child:
    def __init__(self, *args):
        self.messages = queue.Queue()
        self.sent = []
        self.closed = False
    def send(self, value):
        self.sent.append(value)
    def poll(self):
        return None
    def close(self):
        self.closed = True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.remaining = [task('cert-one', 'DIPLOMA'), task('cert-two', 'DEGREE_CERT'),
                          task('report', 'MEDICAL_REPORT')]
        self.store, self.models, self.logger = Mock(), Mock(), Mock()
        self.store.cancelled.return_value = False
        def claim(types, *, lane=None):
            row = next((row for row in self.remaining if types is None or row['doc_type'] in types), None)
            if row:
                self.remaining.remove(row)
            return row
        self.store.claim_next.side_effect = claim
        self.manager = SimpleNamespace(parallel_inference=True, metrics=[])
        self.replies = []
        self.scheduler = TaskScheduler(self.store, self.manager, self.models, Mock(),
                                       self.logger, self.replies.append, factory=Child)

    def finish_stop(self):
        for job in list(self.scheduler.jobs.values()):
            if job.stop_thread:
                job.stop_thread.join(timeout=2)
        self.scheduler._events()

    def test_two_lanes_claim_independently_but_certificate_lane_stays_bounded(self):
        self.scheduler.poll()
        self.assertEqual({j.task['id'] for j in self.scheduler.jobs.values()}, {'cert-one', 'report'})
        self.assertEqual([call.kwargs['lane'] for call in self.store.claim_next.call_args_list],
                         ['certificate', 'medical'])
        self.scheduler.poll()
        self.assertEqual(len(self.scheduler.jobs), 2)
        self.assertEqual([t['id'] for t in self.remaining], ['cert-two'])
        self.scheduler.close()

    def test_photocopy_uses_same_glm_lane_as_ordinary_card(self):
        self.remaining[:] = [task('copy', 'BANK_CARD_COPY'), task('card', 'BANK_CARD'), task('report', 'MEDICAL_REPORT')]
        self.scheduler.poll()
        self.assertEqual({job.task['id']: job.lane for job in self.scheduler.jobs.values()},
                         {'copy': 'certificate', 'report': 'medical'})
        self.assertEqual([row['id'] for row in self.remaining], ['card'])
        self.scheduler.close()

    def test_single_fallback_claims_one_document_at_a_time(self):
        self.scheduler = TaskScheduler(self.store, SimpleNamespace(parallel_inference=False, metrics=[]),
            self.models, Mock(), self.logger, self.replies.append, factory=Child)
        self.scheduler.poll()
        self.assertEqual(len(self.scheduler.jobs), 1)
        self.assertEqual(next(iter(self.scheduler.jobs.values())).task['id'], 'cert-one')
        self.assertEqual(self.store.claim_next.call_args.kwargs, {'lane': 'all'})
        self.scheduler.close()

    def test_photo_tables_share_paddle_lane_and_wait_for_medical_work(self):
        self.remaining.append(task('table','TABLE'))
        self.scheduler.poll()
        self.assertEqual({j.task['id'] for j in self.scheduler.jobs.values()},{'cert-one','report'})
        self.assertIn('table',[t['id'] for t in self.remaining])
        self.scheduler.close()
        self.remaining=[task('table','TABLE'),task('certificate','DIPLOMA')]
        self.scheduler=TaskScheduler(self.store,self.manager,self.models,Mock(),self.logger,self.replies.append,factory=Child)
        self.scheduler.poll()
        self.assertEqual({j.task['doc_type']:j.lane for j in self.scheduler.jobs.values()},{'TABLE':'medical','DIPLOMA':'certificate'})
        self.scheduler.close()

    def test_recognition_replies_return_to_matching_child_without_blocking_other_lane(self):
        self.scheduler.poll()
        jobs = {j.task['id']: j for j in self.scheduler.jobs.values()}
        cert, report = jobs['cert-one'], jobs['report']
        first, second = Future(), Future()
        self.models.submit.side_effect = [first, second]
        for job, key in ((cert, 'glm_ocr'), (report, 'paddleocr_vl')):
            job.child.messages.put(dict(id=1, op='recognize', model=key, task='ocr',
                                        image_base64='synthetic', timeout=10))
        self.scheduler.poll()
        self.assertEqual(self.models.submit.call_count, 2)
        second.set_result({'text': 'synthetic report'})
        self.scheduler.poll()
        self.assertEqual(report.child.sent[0]['result']['text'], 'synthetic report')
        self.assertEqual(cert.child.sent, [])
        first.set_result({'text': 'synthetic cert'})
        self.scheduler.poll()
        self.assertEqual(cert.child.sent[0]['result']['text'], 'synthetic cert')
        for call in self.models.submit.call_args_list:
            self.assertNotIn('timeout', call.args[1])
            self.assertLessEqual(call.kwargs['deadline'], cert.deadline)
        self.scheduler.close()

    def test_generic_forms_share_paddle_lane_without_blocking_certificates(self):
        self.remaining=[task('form','GENERIC'),task('table','TABLE'),task('certificate','DIPLOMA')]
        self.scheduler.poll()
        self.assertEqual({j.task['doc_type']:j.lane for j in self.scheduler.jobs.values()},
                         {'GENERIC':'medical','DIPLOMA':'certificate'})
        self.assertEqual([t['doc_type'] for t in self.remaining],['TABLE'])
        self.scheduler.close()

    def test_pending_stop_never_blocks_poll_or_touches_other_child(self):
        self.scheduler.poll()
        jobs = {j.task['id']: j for j in self.scheduler.jobs.values()}
        cert, report = jobs['cert-one'], jobs['report']
        stopped, release = threading.Event(), threading.Event()
        def stop(*identity):
            stopped.set()
            release.wait(2)
        self.models.stop_run.side_effect = stop
        try:
            self.scheduler.stop_task('cert-one', 'cert-one-run', 91)
            self.assertTrue(stopped.wait(1))
            self.assertEqual(self.replies, [])
            report.child.messages.put(dict(id=1, op='recognize', model='paddleocr_vl', task='table', image_base64='synthetic'))
            self.models.submit.return_value = Future()
            self.scheduler.poll()
            self.models.submit.assert_called_once()
            self.assertFalse(report.child.closed)
        finally:
            release.set()
            self.finish_stop()
            self.scheduler.close()
        reply = next(r for r in self.replies if r['id'] == 91)
        self.assertEqual(reply['result'], dict(stopped=True, task_id='cert-one', run_id='cert-one-run'))
        self.assertEqual(self.models.stop_run.call_args_list[0].args, ('cert-one', 'cert-one-run'))

    def test_old_completed_future_is_discarded_after_target_stop(self):
        self.scheduler.poll()
        cert = next(j for j in self.scheduler.jobs.values() if j.lane == 'certificate')
        future = Future()
        self.models.submit.return_value = future
        cert.child.messages.put(dict(id=1, op='recognize', model='glm_ocr', task='ocr', image_base64='synthetic'))
        self.scheduler.poll()
        self.scheduler.stop_task(cert.task['id'], cert.task['run_id'], 22)
        self.finish_stop()
        future.set_result({'text': 'late synthetic'})
        self.scheduler.poll()
        self.assertEqual(cert.child.sent, [])
        self.assertTrue(cert.child.closed)
        self.scheduler.close()

    def test_stop_failure_never_acknowledges_or_publishes_terminal(self):
        self.scheduler.poll()
        cert = next(j for j in self.scheduler.jobs.values() if j.lane == 'certificate')
        self.models.stop_run.side_effect = RuntimeFailure('SUPERVISION_FAILED')
        self.scheduler.stop_task(cert.task['id'], cert.task['run_id'], 33)
        cert.stop_thread.join(2)
        with self.assertRaises(RuntimeFailure):
            self.scheduler._events()
        self.assertEqual(self.replies, [])
        self.store.finish_stopped.assert_not_called()
        self.models.stop_run.side_effect = None
        for job in self.scheduler.jobs.values():
            if job is not cert:
                self.scheduler._begin_stop(job)
                job.stop_thread.join(2)

    def test_wrong_run_stop_does_not_touch_active_job(self):
        self.scheduler.poll()
        self.scheduler.stop_task('cert-one', 'obsolete-run', 44)
        self.models.stop_run.assert_not_called()
        self.assertFalse(self.replies[-1]['result']['stopped'])
        self.scheduler.close()

    def test_processing_budget_does_not_remove_existing_partial_publication_margin(self):
        self.scheduler.poll()
        jobs = list(self.scheduler.jobs.values())
        for job in jobs:
            job.deadline = 100.
        with patch('ocr_app.task_scheduler.time.monotonic', return_value=100.5):
            self.scheduler.poll()
        self.assertFalse(any(j.stopping for j in jobs))
        self.store.request_stop.assert_not_called()
        with patch('ocr_app.task_scheduler.time.monotonic', return_value=101.):
            self.scheduler.poll()
            for job in jobs:
                job.stop_thread.join(2)
        self.assertTrue(all(j.child.closed for j in jobs))
        calls = [c for c in self.store.request_stop.call_args_list if c.kwargs.get('code') == 'EXTRACT_TIMEOUT']
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.kwargs['deadline'] == 101. for c in calls))
        self.scheduler.close()


if __name__ == '__main__':
    unittest.main()
