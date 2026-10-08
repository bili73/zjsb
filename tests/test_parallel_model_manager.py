"""CPU-only request ownership and independent-model concurrency."""
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, RuntimeFailure


class BlockingFactory:
    def __init__(self):
        self.clients = {}
        self.calls = []
        self.lock = threading.Lock()
    def __call__(self, key, config, phase):
        factory = self
        class Client:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()
                self.dead = False
                self.failure = None
                self.close_count = 0
                self.concurrent = self.max_concurrent = 0
            def call(self, op, timeout, **payload):
                if op == 'load':
                    return {'revision': key + '-revision'}
                with factory.lock:
                    factory.calls.append((key, payload.get('context'), time.monotonic()))
                    self.concurrent += 1
                    self.max_concurrent = max(self.max_concurrent, self.concurrent)
                self.entered.set()
                try:
                    if not self.release.wait(timeout):
                        raise RuntimeFailure('MODEL_REQUEST_TIMEOUT')
                    if self.dead:
                        raise RuntimeFailure('MODEL_PROCESS_EXITED')
                    if self.failure:
                        raise RuntimeFailure(self.failure)
                    return {'text': key, 'termination_reason': 'eos'}
                finally:
                    with factory.lock:
                        self.concurrent -= 1
            def poll(self):
                return 1 if self.dead else None
            def close(self):
                self.close_count += 1
                self.dead = True
                self.release.set()
        client = Client()
        self.clients[key] = client
        return client


class ParallelManagerTests(unittest.TestCase):
    def make(self, mode='dual_resident'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        factory = BlockingFactory()
        manager = ModelManager(RuntimeConfig(Path(temporary.name), mode), factory=factory)
        self.addCleanup(manager.close)
        manager.start()
        return manager, factory

    def test_different_models_overlap_same_model_never_overlaps(self):
        manager, factory = self.make()
        self.assertTrue(manager.parallel_inference)
        with ThreadPoolExecutor(3) as pool:
            a = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2)
            b = pool.submit(manager.recognize, 'paddleocr_vl', 'x', timeout=2)
            self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
            self.assertTrue(factory.clients['paddleocr_vl'].entered.wait(1))
            c = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2)
            time.sleep(.03)
            self.assertEqual(len(factory.calls), 2)
            for client in factory.clients.values():
                client.release.set()
            self.assertEqual(a.result(1)['model_revision'], 'glm_ocr-revision')
            b.result(1); c.result(1)
        self.assertEqual(factory.clients['glm_ocr'].max_concurrent, 1)

    def test_stop_run_kills_only_owner_and_old_stop_cannot_kill_other_model(self):
        manager, factory = self.make()
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2,
                            context={'task_id': 'a', 'run_id': 'old'})
            b = pool.submit(manager.recognize, 'paddleocr_vl', 'x', timeout=2,
                            context={'task_id': 'b', 'run_id': 'current'})
            for client in factory.clients.values():
                self.assertTrue(client.entered.wait(1))
            manager.stop_run('a', 'old')
            with self.assertRaises(RuntimeFailure):
                a.result(1)
            self.assertFalse(factory.clients['paddleocr_vl'].dead)
            manager.stop_run('a', 'old')
            factory.clients['paddleocr_vl'].release.set()
            self.assertEqual(b.result(1)['termination_reason'], 'eos')
        with self.assertRaises(RuntimeFailure):
            manager.recognize('glm_ocr', 'x', timeout=1)
        self.assertFalse(factory.clients['paddleocr_vl'].dead)

    def test_oom_disables_one_model_without_unloading_or_recovering_peer(self):
        manager, factory = self.make()
        factory.clients['glm_ocr'].failure = 'RESOURCE_LIMIT'
        factory.clients['glm_ocr'].release.set()
        with self.assertRaises(RuntimeFailure):
            manager.recognize('glm_ocr', 'x', timeout=1)
        self.assertNotIn('glm_ocr', manager.pending_recovery)
        self.assertFalse(factory.clients['paddleocr_vl'].dead)
        self.assertEqual(manager.snapshot()['models']['glm_ocr'], 'failed')

    def test_late_stop_of_completed_run_does_not_kill_new_owner_same_process(self):
        manager, factory = self.make()
        client = factory.clients['glm_ocr']
        client.release.set()
        manager.recognize('glm_ocr', 'x', context={'task_id': 'task', 'run_id': 'old'})
        client.release.clear(); client.entered.clear()
        with ThreadPoolExecutor(1) as pool:
            running = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2,
                                  context={'task_id': 'task', 'run_id': 'new'})
            self.assertTrue(client.entered.wait(1))
            manager.stop_run('task', 'old')
            self.assertFalse(client.dead)
            client.release.set(); running.result(1)

    def test_stop_fences_process_reuse_before_physical_close(self):
        manager, factory = self.make()
        client = factory.clients['glm_ocr']
        closing, allow_close = threading.Event(), threading.Event()
        original = manager._unload
        def delayed(key, expected_client=None):
            if expected_client is client:
                closing.set()
                allow_close.wait(1)
            return original(key, expected_client)
        with patch.object(manager, '_unload', side_effect=delayed), ThreadPoolExecutor(2) as pool:
            old = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2,
                              context={'task_id': 'task', 'run_id': 'old'})
            self.assertTrue(client.entered.wait(1))
            stopping = pool.submit(manager.stop_run, 'task', 'old')
            self.assertTrue(closing.wait(1))
            client.release.set()
            with self.assertRaises(RuntimeFailure):
                old.result(1)
            with self.assertRaises(RuntimeFailure):
                manager.recognize('glm_ocr', 'x', timeout=.2, context={'task_id': 'task', 'run_id': 'new'})
            self.assertEqual(len(factory.calls), 1)
            allow_close.set(); stopping.result(1)

    def test_single_mode_serializes_different_models_and_retains_switch(self):
        manager, factory = self.make('single_resident')
        self.assertFalse(manager.parallel_inference)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(manager.recognize, 'glm_ocr', 'x', timeout=2)
            self.assertTrue(factory.clients['glm_ocr'].entered.wait(1))
            second = pool.submit(manager.recognize, 'paddleocr_vl', 'x', timeout=2)
            time.sleep(.03)
            self.assertEqual(set(factory.clients), {'glm_ocr'})
            factory.clients['glm_ocr'].release.set(); first.result(1)
            until = time.monotonic() + 1
            while 'paddleocr_vl' not in factory.clients and time.monotonic() < until:
                time.sleep(.005)
            self.assertTrue(factory.clients['glm_ocr'].dead)
            factory.clients['paddleocr_vl'].release.set(); second.result(1)

    def test_stop_before_cold_spawn_keeps_peer_and_clears_stopping_state(self):
        manager, factory = self.make('single_resident')
        entered, proceed = threading.Event(), threading.Event()
        original = manager._recognize_owned
        def delayed(*args, **kwargs):
            entered.set(); proceed.wait(1)
            return original(*args, **kwargs)
        with patch.object(manager, '_recognize_owned', side_effect=delayed), ThreadPoolExecutor(2) as pool:
            call = pool.submit(manager.recognize, 'paddleocr_vl', 'x', timeout=2,
                               context={'task_id': 'a', 'run_id': 'a'})
            self.assertTrue(entered.wait(1))
            stopping = pool.submit(manager.stop_run, 'a', 'a')
            until = time.monotonic() + 1
            while time.monotonic() < until:
                if manager.snapshot()['models']['paddleocr_vl'] == 'stopping':
                    break
                time.sleep(.005)
            proceed.set(); stopping.result(1)
            with self.assertRaisesRegex(RuntimeFailure, 'CANCELLED'):
                call.result(1)
        self.assertNotIn('paddleocr_vl', factory.clients)
        self.assertFalse(factory.clients['glm_ocr'].dead)
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'], 'failed')


if __name__ == '__main__':
    unittest.main()
