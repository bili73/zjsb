import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from model_worker import Engine


class ModelCheckpointTests(unittest.TestCase):
    def test_legacy_default_and_explicit_upgrade_keep_public_identity(self):
        legacy = Engine('paddleocr-vl')
        upgraded = Engine('paddleocr-vl', 'paddleocr-vl-1.6')
        self.assertEqual(legacy.checkpoint_name, 'paddleocr-vl')
        self.assertEqual(upgraded.checkpoint_name, 'paddleocr-vl-1.6')
        self.assertEqual(upgraded.name, legacy.name)

    def test_reject_cross_family_and_arbitrary_paths_before_loading(self):
        for model, checkpoint in [('glm-ocr', 'paddleocr-vl-1.6'),
                                  ('paddleocr-vl', 'glm-ocr'),
                                  ('paddleocr-vl', '../external'),
                                  ('unknown', 'paddleocr-vl')]:
            with self.subTest(model=model, checkpoint=checkpoint):
                with self.assertRaises(ValueError):
                    Engine(model, checkpoint)


if __name__ == '__main__':
    unittest.main()
