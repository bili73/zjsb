"""CPU FIFO expiry/cancellation/fallback regressions."""
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.model_queues import ModelQueues
from ocr_app.runtime import RuntimeFailure
from ocr_app.runtime import ModelManager
from ocr_app.config import RuntimeConfig
import test_parallel_model_manager as helpers


class ModelQueueTests(unittest.TestCase):
    make = helpers.ParallelManagerTests.make
    def queues(self):
        manager, factory = self.make()
        queues = ModelQueues(manager)
        self.addCleanup(queues.close)
        return queues, manager, factory

    def submit(self, queues, model, run, duration=2):
        return queues.submit(model, {'image': 'x'}, task_id=run, run_id=run,
                             request_id=run, deadline=time.monotonic() + duration)

    def test_queued_expiry_does_not_kill_active_other_run(self):
        queues, manager, factory = self.queues()
        active = self.submit(queues, 'glm_ocr', 'first')
        self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
        expired = self.submit(queues, 'glm_ocr', 'second', .08)
        with self.assertRaisesRegex(RuntimeFailure, 'EXTRACT_TIMEOUT'):
            expired.result(.5)
        self.assertFalse(factory.clients['glm_ocr'].dead)
        self.assertEqual(len(factory.calls), 1)
        factory.clients['glm_ocr'].release.set()
        active.result(1)

    def test_queued_cancel_and_late_submission_cannot_start_or_kill_peer(self):
        queues, manager, factory = self.queues()
        active = self.submit(queues, 'glm_ocr', 'first')
        self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
        pending = self.submit(queues, 'glm_ocr', 'cancel')
        queues.stop_run('cancel', 'cancel')
        for future in (pending, self.submit(queues, 'paddleocr_vl', 'cancel')):
            with self.assertRaisesRegex(RuntimeFailure, 'CANCELLED'):
                future.result(1)
        self.assertFalse(factory.clients['glm_ocr'].dead)
        factory.clients['glm_ocr'].release.set(); active.result(1)

    def test_fallback_joins_other_fifo_without_holding_first_model(self):
        queues, manager, factory = self.queues()
        factory.clients['paddleocr_vl'].release.set()
        self.submit(queues, 'paddleocr_vl', 'medical').result(1)
        certificate = self.submit(queues, 'glm_ocr', 'certificate')
        self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
        fallback = self.submit(queues, 'glm_ocr', 'medical')
        self.submit(queues, 'paddleocr_vl', 'next').result(1)
        self.assertFalse(fallback.done())
        factory.clients['glm_ocr'].release.set()
        certificate.result(1); fallback.result(1)

    def test_stop_inflight_confirms_exit_but_other_model_completes(self):
        queues, manager, factory = self.queues()
        a = self.submit(queues, 'glm_ocr', 'a')
        b = self.submit(queues, 'paddleocr_vl', 'b')
        for client in factory.clients.values():
            self.assertTrue(client.entered.wait(1))
        queues.stop_run('a', 'a')
        self.assertTrue(a.done())
        self.assertTrue(factory.clients['glm_ocr'].dead)
        self.assertFalse(factory.clients['paddleocr_vl'].dead)
        factory.clients['paddleocr_vl'].release.set(); b.result(1)

    def test_close_resolves_pending_and_stops_all_consumers(self):
        queues, manager, factory = self.queues()
        a = self.submit(queues, 'glm_ocr', 'a')
        self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
        b = self.submit(queues, 'glm_ocr', 'b')
        queues.close()
        self.assertTrue(a.done() and b.done())
        self.assertTrue(all(c.dead for c in factory.clients.values()))
        self.assertTrue(all(not t.is_alive() for t in queues.threads))

    def test_stop_between_consumer_pop_and_manager_dispatch_never_starts_model(self):
        queues, manager, factory = self.queues()
        popped, dispatch = threading.Event(), threading.Event()
        original = manager.recognize
        def delayed(*args, **kwargs):
            popped.set()
            dispatch.wait(1)
            return original(*args, **kwargs)
        with patch.object(manager, 'recognize', side_effect=delayed), ThreadPoolExecutor(1) as pool:
            result = self.submit(queues, 'glm_ocr', 'cancel')
            self.assertTrue(popped.wait(1))
            stopped = pool.submit(queues.stop_run, 'cancel', 'cancel')
            time.sleep(.03)
            dispatch.set(); stopped.result(1)
            with self.assertRaisesRegex(RuntimeFailure, 'CANCELLED'):
                result.result(1)
        self.assertFalse(factory.calls)
        self.assertTrue(all(not c.dead for c in factory.clients.values()))

    def test_fifo_wait_is_reported_and_callback_can_stop_completed_run(self):
        queues, manager, factory = self.queues()
        first = self.submit(queues, 'glm_ocr', 'first')
        self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
        second = self.submit(queues, 'glm_ocr', 'second')
        callback_done = threading.Event()
        def callback(future):
            queues.stop_run('second', 'second')
            callback_done.set()
        second.add_done_callback(callback)
        time.sleep(.04)
        factory.clients['glm_ocr'].release.set(); first.result(1)
        self.assertGreaterEqual(second.result(1)['queue_wait_seconds'], .03)
        self.assertTrue(callback_done.wait(1))
        self.assertFalse(factory.clients['glm_ocr'].dead)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job supervision')
    def test_real_cpu_child_stop_does_not_close_other_model_job(self):
        class CPUConfig(RuntimeConfig):
            def model_command(self, key):
                code = "import json,sys,time\nfor line in sys.stdin:\n r=json.loads(line)\n if r['op']=='load': print(json.dumps({'id':r['id'],'ok':True,'result':{'revision':'cpu'}}),flush=True)\n else: time.sleep(60)\n"
                return [sys.executable, '-u', '-c', code]
        with tempfile.TemporaryDirectory() as directory:
            manager = ModelManager(CPUConfig(Path(directory), load_timeout=3))
            manager.start()
            queues = ModelQueues(manager)
            try:
                left, right = manager.clients['glm_ocr'], manager.clients['paddleocr_vl']
                a = self.submit(queues, 'glm_ocr', 'left', 5)
                b = self.submit(queues, 'paddleocr_vl', 'right', 5)
                until = time.monotonic() + 1
                while time.monotonic() < until:
                    with manager._state:
                        if len(manager._owners) == 2:
                            break
                    time.sleep(.005)
                queues.stop_run('left', 'left')
                self.assertIsNotNone(left.poll())
                self.assertIsNone(right.poll())
                self.assertTrue(a.done())
                self.assertFalse(b.done())
            finally:
                queues.close()
            self.assertIsNotNone(right.poll())


if __name__ == '__main__':
    unittest.main()
