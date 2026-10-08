"""CPU-only regressions for fatal supervision and invalid worker protocols."""

import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from ocr_app.client import RuntimeClient
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, RuntimeFailure


class FakeProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("not-json\n")
        self.stderr = io.StringIO()
        self.closed = False

    def poll(self):
        return 1 if self.closed else None

    def kill_tree(self):
        self.closed = True

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, load_failures=(), failing_close_indices=()):
        self.load_failures = list(load_failures)
        self.failing_close_indices = set(failing_close_indices)
        self.events = []
        self.instances = []

    def __call__(self, key, config, phase):
        factory = self
        index = len(self.instances)

        class Client:
            dead = False
            close_failed = False

            def call(self, operation, timeout, **payload):
                factory.events.append((operation, key))
                if operation == "load" and factory.load_failures:
                    code = factory.load_failures.pop(0)
                    if code:
                        raise RuntimeFailure(code)
                return {}

            def close(self):
                factory.events.append(("close", key))
                if index in factory.failing_close_indices and not self.close_failed:
                    self.close_failed = True
                    raise OSError("simulated uncertain process-tree cleanup")
                self.dead = True

            def poll(self):
                return 1 if self.dead else None

        instance = Client()
        self.instances.append(instance)
        return instance


class RuntimeFailClosedTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="ocr-fail-closed-")
        self.addCleanup(directory.cleanup)
        self.config = RuntimeConfig(Path(directory.name), "single_resident")

    def assert_supervision_failure(self, operation):
        with self.assertRaises(RuntimeFailure) as caught:
            operation()
        self.assertEqual(caught.exception.code, "SUPERVISION_FAILED")

    def test_invalid_json_reclaims_runtime_and_invalidates_liveness(self):
        client = RuntimeClient(self.config)
        fake = FakeProcess()
        client.process = fake
        self.assertTrue(client.is_alive())
        client._read()
        self.assertTrue(fake.closed, "broken protocol must reclaim the worker tree")
        self.assertFalse(client.is_alive())
        self.assertEqual(client.snapshot()["effective_mode"], "ocr_unavailable")

    def test_failed_close_blocks_all_future_recognition(self):
        factory = FakeFactory(failing_close_indices={0})
        manager = ModelManager(self.config, factory=factory)
        self.addCleanup(manager.close)
        manager.start()
        self.assert_supervision_failure(lambda: manager.recognize("paddleocr_vl", "unused"))
        before = list(factory.events)
        self.assert_supervision_failure(lambda: manager.recognize("glm_ocr", "unused"))
        self.assert_supervision_failure(lambda: manager.recognize("paddleocr_vl", "unused"))
        self.assertEqual(factory.events, before, "fatal state must not dispatch more model operations")

    def test_startup_recovery_does_not_swallow_supervision_failure(self):
        factory = FakeFactory(load_failures=["RESOURCE_LIMIT", "MODEL_LOAD_FAILED"],
                              failing_close_indices={1})
        manager = ModelManager(self.config, factory=factory)
        self.addCleanup(manager.close)
        self.assert_supervision_failure(manager.start)
        before = list(factory.events)
        self.assert_supervision_failure(lambda: manager.recognize("glm_ocr", "unused"))
        self.assertEqual(factory.events, before)


if __name__ == "__main__":
    unittest.main()
