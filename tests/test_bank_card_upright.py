"""Bank direction uses an internal card view while preserving the complete source."""
import base64
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app import image_preprocessing as prep
from ocr_app.documents import png_bytes
from ocr_app.pipeline import process_document


def photo():
    image = Image.new('RGB', (800, 1000), (190, 175, 155))
    draw = ImageDraw.Draw(image)
    draw.rectangle((250, 220, 550, 720), fill=(30, 50, 120))
    draw.text((270, 250), 'BANK 4111 1111', fill='white')
    draw.rectangle((5, 5, 20, 20), fill='red')
    return image


class BankCardUprightTests(unittest.TestCase):
    def test_geometry_finds_card_and_removes_background_only_from_analysis_view(self):
        original = photo()
        view = prep._bank_card_view(original)
        self.assertIsNotNone(view)
        self.assertLess(view.width, original.width // 2)
        self.assertLess(view.height, original.height * .6)
        self.assertGreaterEqual(view.width, 301)
        self.assertGreaterEqual(view.height, 501)
        self.assertEqual(view.getpixel((view.width // 2, view.height // 2)), (30, 50, 120))
        self.assertEqual(original.size, (800, 1000))
        self.assertEqual(original.getpixel((10, 10)), (255, 0, 0))

    def test_confident_card_crop_returns_its_direction_without_extra_views(self):
        card = Image.new('RGB', (260, 400), 'blue')
        with patch.object(prep, '_bank_card_view', return_value=card), patch.object(prep, 'classify_orientation', return_value=(270, .95, .8)) as classify:
            self.assertEqual(prep.classify_bank_orientation(photo()), (270, .95, .8))
        classify.assert_called_once_with(card)

    def test_landscape_normalization_composes_quarter_turn_and_flip(self):
        card = Image.new('RGB', (260, 400), 'blue')
        with patch.object(prep, '_bank_card_view', return_value=card), patch.object(prep, 'classify_orientation', side_effect=[(90, .8, .6), (180, .96, .8)]) as classify:
            self.assertEqual(prep.classify_bank_orientation(photo()), (270, .96, .8))
        self.assertEqual(classify.call_count, 2)
        self.assertEqual(classify.call_args.args[0].size, (400, 260))

    def test_padding_retries_same_threshold_without_repeating_landscape_view(self):
        card = Image.new('RGB', (400, 260), 'blue')
        with patch.object(prep, '_bank_card_view', return_value=card), patch.object(prep, 'classify_orientation', side_effect=[(180, .899, .8), (180, .96, .8)]) as classify:
            self.assertEqual(prep.classify_bank_orientation(photo()), (180, .96, .8))
        self.assertEqual(classify.call_count, 2)
        self.assertEqual(classify.call_args.args[0].size, (424, 284))

    def test_unconfident_or_inconsistent_card_views_preserve_complete_photo(self):
        for prediction in [(90, .899, .8), (90, .99, .24), (0, 0., 0.)]:
            with self.subTest(prediction=prediction):
                image = photo()
                with patch.object(prep, '_bank_card_view', return_value=Image.new('RGB', (260, 400), 'blue')), patch.object(prep, 'classify_orientation', return_value=prediction), patch.object(prep, 'estimate_skew') as skew:
                    corrected, decision = prep.prepare_image(image, doc_type='BANK_CARD')
                self.assertEqual(corrected.tobytes(), image.tobytes())
                self.assertEqual(decision['rotation_degrees'], 0)
                self.assertEqual(decision['warning'], 'IMAGE_UPRIGHT_UNCERTAIN')
                skew.assert_not_called()

    def test_no_detected_card_uses_existing_full_photo_classifier(self):
        image = photo()
        with patch.object(prep, '_bank_card_view', return_value=None), patch.object(prep, 'classify_orientation', return_value=(90, .98, .9)) as classify:
            self.assertEqual(prep.classify_bank_orientation(image), (90, .98, .9))
        classify.assert_called_once_with(image)

    def test_bank_pipeline_turns_entire_photo_and_reuses_decision_on_pass_two(self):
        image = photo()
        expected = image.transpose(Image.Transpose.ROTATE_90)
        saved, inputs, attempts = [], [], []
        def save(index, content, width, height):
            saved.append(Image.open(io.BytesIO(content)).convert('RGB'))
            self.assertEqual((width, height), expected.size)
            return '9fd1a42b-95fd-4c78-b946-907f15b2093d'
        def recognize(model, content, kind, timeout):
            inputs.append(Image.open(io.BytesIO(base64.b64decode(content))).convert('RGB'))
            return dict(text='卡号 4111 1111 1111 1111', termination_reason='eos')
        with patch.object(prep, 'classify_bank_orientation', return_value=(90, .99, .9)) as classify, patch.object(prep, 'estimate_skew', return_value=(0., 'already_level')):
            result = process_document(png_bytes(image), 'BANK_CARD', recognize=recognize,
                save_page=save, record_attempt=attempts.append, progress=lambda *a: None,
                cancelled=lambda: False, deadline=time.monotonic() + 20)
        classify.assert_called_once()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].tobytes(), expected.tobytes())
        self.assertEqual(inputs[0].tobytes(), expected.tobytes())
        metadata = result['pages'][0]['image_preprocessing']
        self.assertEqual(metadata['version'], 'bank-card-upright-v1')
        self.assertEqual(metadata, attempts[0]['image_preprocessing'])

    def test_nonbank_inputs_do_not_use_bank_detector(self):
        for kind in [None, 'DIPLOMA', 'DEGREE_CERT', 'ID_CARD_FRONT', 'PASSPORT']:
            with self.subTest(kind=kind), patch.object(prep, '_bank_card_view') as detector, patch.object(prep, 'classify_orientation', return_value=(0, .99, .9)), patch.object(prep, 'estimate_skew', return_value=(0., 'already_level')):
                _, decision = prep.prepare_image(photo(), doc_type=kind)
                self.assertEqual(decision['version'], 'certificate-upright-v1')
                detector.assert_not_called()

    def test_cancel_during_card_detection_propagates_without_classifying(self):
        class Cancelled(Exception):
            pass
        checks = 0
        def check():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise Cancelled()
        with patch.object(prep, 'classify_orientation') as classify, self.assertRaises(Cancelled):
            prep.classify_bank_orientation(photo(), check)
        classify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
