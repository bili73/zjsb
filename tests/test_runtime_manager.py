import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, RuntimeFailure


class FakeFactory:
    def __init__(self, failures=None):
        self.failures = failures or {}
        self.events = []
        self.instances = []

    def __call__(self, key, config, phase):
        factory = self
        class Fake:
            dead = False
            def call(self, operation, timeout, **payload):
                factory.events.append((operation, key))
                planned = factory.failures.get((key, operation), [])
                if planned:
                    code = planned.pop(0)
                    if code:
                        raise RuntimeFailure(code)
                if operation == 'load':
                    phase(key, 'warming')
                return {'text': 'test'} if operation == 'recognize' else {}
            def poll(self):
                return 1 if self.dead else None
            def close(self):
                factory.events.append(('close', key))
                self.dead = True
        instance = Fake()
        self.instances.append(instance)
        return instance


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make(self, mode='dual_resident', failures=None):
        factory = FakeFactory(failures)
        manager = ModelManager(RuntimeConfig(Path(self.temp.name), mode), factory=factory)
        self.addCleanup(manager.close)
        return manager, factory

    def test_dual_startup_reuses_both_and_serializes_requests(self):
        manager, factory = self.make()
        manager.start()
        self.assertEqual(manager.snapshot()['effective_mode'], 'dual_resident')
        manager.recognize('paddleocr_vl', 'unused')
        manager.recognize('glm_ocr', 'unused')
        self.assertEqual(factory.events, [('load', 'glm_ocr'), ('load', 'paddleocr_vl'),
                                          ('recognize', 'paddleocr_vl'), ('recognize', 'glm_ocr')])

    def test_single_switch_closes_old_tree_before_loading(self):
        manager, factory = self.make('single_resident')
        manager.start()
        manager.recognize('paddleocr_vl', 'unused')
        self.assertEqual(factory.events[:3], [('load', 'glm_ocr'), ('close', 'glm_ocr'), ('load', 'paddleocr_vl')])
        self.assertEqual(set(manager.clients), {'paddleocr_vl'})
        self.assertEqual(manager.snapshot()['configured_mode'], 'single_resident')

    def test_oom_fallback_only_one_isolated_recovery_then_no_retry(self):
        manager, factory = self.make(failures={('paddleocr_vl', 'load'): ['RESOURCE_LIMIT', 'RESOURCE_LIMIT']})
        manager.start()
        view = manager.snapshot()
        self.assertEqual(view['configured_mode'], 'dual_resident')
        self.assertEqual(view['effective_mode'], 'single_resident')
        self.assertEqual(view['reason_code'], 'RESOURCE_LIMIT')
        with self.assertRaises(RuntimeFailure):
            manager.recognize('paddleocr_vl', 'unused')
        before = list(factory.events)
        for _ in range(3):
            manager.check_processes()
            with self.assertRaises(RuntimeFailure):
                manager.recognize('paddleocr_vl', 'unused')
        self.assertEqual(factory.events, before)
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'], 'failed')

    def test_dependency_error_is_not_resource_fallback(self):
        manager, factory = self.make(failures={('glm_ocr', 'load'): ['MODEL_LOAD_FAILED']})
        manager.start()
        self.assertEqual(manager.snapshot()['reason_code'], 'MODEL_LOAD_FAILED')
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'], 'ready')
        with self.assertRaises(RuntimeFailure):
            manager.recognize('glm_ocr', 'unused')
        self.assertEqual(set(manager.clients), {'paddleocr_vl'})

    def test_process_exit_invalidates_readiness_without_restarting(self):
        manager, factory = self.make()
        manager.start()
        factory.instances[0].dead = True
        manager.check_processes()
        self.assertEqual(manager.snapshot()['models']['glm_ocr'], 'failed')
        self.assertEqual(manager.snapshot()['reason_code'], 'MODEL_PROCESS_EXITED')
        self.assertEqual(factory.events.count(('load', 'glm_ocr')), 1)

    def test_bad_input_does_not_poison_a_ready_model(self):
        manager, _ = self.make(failures={('glm_ocr', 'recognize'): ['INPUT_INVALID']})
        manager.start()
        with self.assertRaises(RuntimeFailure):
            manager.recognize('glm_ocr', 'unused')
        self.assertEqual(manager.snapshot()['models']['glm_ocr'], 'ready')

    def test_inference_oom_does_not_silently_repeat_region(self):
        manager, factory = self.make(failures={('glm_ocr', 'recognize'): ['RESOURCE_LIMIT']})
        manager.start()
        with self.assertRaises(RuntimeFailure):
            manager.recognize('glm_ocr', 'unused')
        self.assertEqual(factory.events.count(('recognize', 'glm_ocr')), 1)
        self.assertEqual(manager.snapshot()['effective_mode'], 'single_resident')
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'], 'ready')


if __name__ == '__main__':
    unittest.main()
