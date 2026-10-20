"""CPU-only protocol and fail-closed tests; no model processes are launched."""
import contextlib
import io
import queue
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import runtime_worker
from ocr_app.runtime import RuntimeFailure


TASK = dict(id='task-fixture', run_id='run-fixture', input_ref='encrypted-input',
            options_enc='encrypted-options', doc_type='MEDICAL_REPORT')


def fake_store():
    store = Mock()
    store.storage.read.return_value = b'controlled fixture'
    store.storage.unpack.return_value = {}
    store.cancelled.return_value = False
    store.save_page.return_value = 'page-fixture'
    store.required_policy.return_value = dict(revision=0, overrides={})
    store.claim_next.return_value = TASK
    return store


class WorkerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.store, self.manager, self.logger = fake_store(), Mock(), Mock()
        self.manager.metrics = []
        self.logger.exception.return_value = 'error-fixture'

    def test_pipeline_library_stdout_does_not_pollute_protocol(self):
        def pipeline(*args, **kwargs):
            print('synthetic library diagnostic')
            kwargs['progress']('EXTRACTING', 70, [])
            return dict(status='NEED_REVIEW', pages=[], fields=[], review_issues=[])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch('ocr_app.pipeline.process_document', side_effect=pipeline):
            runtime_worker.process_task(self.store, self.manager, TASK, self.logger)
        self.assertEqual(stdout.getvalue(), '')
        self.store.publish.assert_called_once()
        self.assertEqual(self.store.publish.call_args.args[1]['status'], 'NEED_REVIEW')

    def test_supervision_failure_escapes_task_and_never_reports_completed(self):
        with patch('ocr_app.pipeline.process_document', side_effect=RuntimeFailure('SUPERVISION_FAILED')):
            with self.assertRaises(RuntimeFailure) as caught:
                runtime_worker.process_task(self.store, self.manager, TASK, self.logger)
        self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
        names = [call.args[0] for call in self.logger.event.call_args_list]
        self.assertNotIn('task_completed', names)

    def test_task_callbacks_forward_region_context_and_shared_budget(self):
        seen = {}
        def pipeline(content, doc_type, **kwargs):
            seen.update(kwargs)
            kwargs['recognize']('paddleocr_vl', 'base64-fixture', 'table', 17.5,
                                context=dict(page=3, region_id='region-fixture', stage='OCR'))
            kwargs['record_attempt'](dict(attempt=1, page_index=3, model='paddleocr_vl', task='table'))
            kwargs['save_page'](3, b'png-fixture', 100, 200)
            return dict(status='NEED_REVIEW', pages=[], fields=[], review_issues=[])
        with patch('ocr_app.pipeline.process_document', side_effect=pipeline):
            runtime_worker.process_task(self.store, self.manager, TASK, self.logger)
        forwarded = self.manager.recognize.call_args.kwargs
        self.assertEqual(forwarded['timeout'], 17.5)
        self.assertEqual(forwarded['context'], dict(task_id='task-fixture', run_id='run-fixture',
                                                   page=3, region_id='region-fixture', stage='OCR'))
        self.assertEqual(forwarded['task'], 'table')
        self.assertIsInstance(seen['deadline'], float)
        self.store.attempt.assert_called_once()
        self.assertEqual(self.store.attempt.call_args.args[1]['prompt'], 'Table Recognition:')
        self.store.save_page.assert_called_once_with(TASK, 3, b'png-fixture', 100, 200)

    def test_protocol_emit_remains_on_its_saved_stream_during_pipeline(self):
        stdout, stderr, protocol = io.StringIO(), io.StringIO(), io.StringIO()
        def pipeline(*args, **kwargs):
            print('synthetic library notice')
            runtime_worker.emit({'event': 'snapshot', 'runtime': {'state': 'ready'}})
            return dict(status='NEED_REVIEW', pages=[], fields=[], review_issues=[])
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch.object(runtime_worker, 'OUT', protocol), \
                patch('ocr_app.pipeline.process_document', side_effect=pipeline):
            runtime_worker.process_task(self.store, self.manager, TASK, self.logger)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(protocol.getvalue().count('\n'), 1)
        self.assertNotIn('library', protocol.getvalue())
        self.assertIn('snapshot', protocol.getvalue())

    def test_certificate_recovery_receives_current_required_policy_snapshot(self):
        policy = dict(revision=7, overrides={'DIPLOMA': ['major', 'birth_date']})
        self.store.required_policy.return_value = policy
        with patch('ocr_app.pipeline.process_document', return_value=dict(status='NEED_REVIEW')) as pipeline:
            runtime_worker.process_task(self.store, self.manager, dict(TASK, doc_type='DIPLOMA'), self.logger)
        self.assertEqual(pipeline.call_args.kwargs['required_overrides'], policy['overrides'])
        self.store.required_policy.assert_called_once_with()

    def test_local_recovery_policy_is_forwarded_to_the_model_owner(self):
        context = dict(page=1, region_id='crop', stage='OCR', batch_policy='single')
        def pipeline(*args, **kwargs):
            kwargs['recognize']('glm_ocr', 'synthetic', context=context)
            return dict(status='NEED_REVIEW')
        with patch('ocr_app.pipeline.process_document', side_effect=pipeline):
            runtime_worker.process_task(self.store, self.manager, dict(TASK, doc_type='DIPLOMA'), self.logger)
        passed = self.manager.recognize.call_args.kwargs['context']
        self.assertEqual(passed['batch_policy'], 'single')
        self.assertEqual(passed['task_id'], TASK['id'])
        self.assertEqual(passed['run_id'], TASK['run_id'])

    def test_main_closes_manager_and_stops_claiming_after_fatal_task(self):
        inbox = Mock()
        inbox.get.side_effect = [queue.Empty(), None]
        completed = queue.Queue()
        models, scheduler = Mock(), Mock()
        scheduler.poll.side_effect = RuntimeFailure('SUPERVISION_FAILED')
        args = types.SimpleNamespace(mode='dual_resident', session_dir=Path('unused-session'), data_root=Path('unused-data'), model_batch_size=1)
        with patch.object(runtime_worker.argparse.ArgumentParser, 'parse_args', return_value=args), \
                patch.object(runtime_worker, 'RuntimeConfig', return_value=Mock()), \
                patch.object(runtime_worker, 'ModelManager', return_value=self.manager), \
                patch.object(runtime_worker, 'session_diagnostics', return_value=self.logger), \
                patch.object(runtime_worker.queue, 'Queue', side_effect=[inbox, completed]), \
                patch.object(runtime_worker.threading, 'Thread'), \
                patch('ocr_app.storage.Storage'), patch('ocr_app.db.open_database'), \
                patch('ocr_app.task_store.TaskStore', return_value=self.store), \
                patch('ocr_app.model_queues.ModelQueues', return_value=models), \
                patch('ocr_app.task_scheduler.TaskScheduler', return_value=scheduler):
            with self.assertRaises(RuntimeFailure) as caught:
                runtime_worker.main()
            self.assertEqual(caught.exception.code, 'SUPERVISION_FAILED')
        inbox.get.assert_not_called()
        scheduler.poll.assert_called_once()
        scheduler.close.assert_called_once()
        models.close.assert_called_once()
        self.store.engine.dispose.assert_called_once()

    def test_private_recognition_uses_isolated_rpc_owner_and_shared_queue(self):
        models = Mock()
        config = types.SimpleNamespace(request_timeout=180)
        with patch.object(runtime_worker.time, 'monotonic', return_value=100):
            runtime_worker.submit_recognition(models, config, dict(id=7, model='glm_ocr',
                image_base64='synthetic', timeout=11, context={'task_id': 'external'}))
        args, kwargs = models.submit.call_args
        self.assertEqual(args, ('glm_ocr', {'image_base64': 'synthetic', 'task': 'ocr'}))
        self.assertEqual((kwargs['task_id'], kwargs['run_id']), ('rpc-7', 'private-rpc'))
        self.assertEqual(kwargs['deadline'], 111)

    def test_claimed_deadline_includes_cpu_worker_startup(self):
        def pipeline(*args, **kwargs):
            self.assertEqual(kwargs['deadline'], 321.)
            return dict(status='NEED_REVIEW', pages=[], fields=[], review_issues=[])
        with patch('ocr_app.pipeline.process_document', side_effect=pipeline):
            runtime_worker.process_task(self.store, self.manager, TASK, self.logger, deadline=321.)


if __name__ == '__main__':
    unittest.main()
