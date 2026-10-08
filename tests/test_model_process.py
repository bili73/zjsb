import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, ModelProcess, RuntimeFailure


FAKE = """
import json,sys,time
for line in sys.stdin:
    request=json.loads(line)
    if request['op']=='load':
        print(json.dumps({'id':request['id'],'ok':True,'result':{}}),flush=True)
    else:
        time.sleep(60)
"""


class FakeConfig(RuntimeConfig):
    def model_command(self, key):
        return [sys.executable, '-u', '-c', FAKE]


@unittest.skipUnless(os.name == 'nt', 'Windows Job supervision')
class ProcessTests(unittest.TestCase):
    def test_hung_recognition_is_killed_and_cannot_stay_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ModelManager(FakeConfig(Path(directory), 'single_resident', load_timeout=3))
            try:
                manager.start()
                client = manager.clients['glm_ocr']
                begin = time.monotonic()
                with self.assertRaisesRegex(RuntimeFailure, 'MODEL_REQUEST_TIMEOUT'):
                    manager.recognize('glm_ocr', 'unused', timeout=.1)
                self.assertLess(time.monotonic() - begin, 4)
                self.assertIsNotNone(client.poll())
                self.assertEqual(manager.snapshot()['models']['glm_ocr'], 'failed')
                self.assertNotIn('glm_ocr', manager.clients)
            finally:
                manager.close()

    def test_missing_phase_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            class BadConfig(FakeConfig):
                def model_command(self, key):
                    return [sys.executable, '-u', '-c',
                            "import sys,time; sys.stdin.readline(); print('{\"event\":\"phase\"}',flush=True); time.sleep(60)"]
            process = ModelProcess('glm_ocr', BadConfig(Path(directory)), lambda *args: None)
            try:
                with self.assertRaisesRegex(RuntimeFailure, 'MODEL_LOAD_FAILED'):
                    process.call('load', timeout=2)
            finally:
                process.close()
            self.assertIsNotNone(process.poll())


if __name__ == '__main__':
    unittest.main()
