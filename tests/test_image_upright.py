"""Image preparation preserves uncertain input, source geometry and task deadlines."""
import base64
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.documents import decode_pages, png_bytes
from ocr_app.image_preprocessing import apply_correction, estimate_skew, prepare_image, classify_orientation
from ocr_app.pipeline import process_document


def document():
    image = Image.new('RGB', (800, 620), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    for row in range(10):
        draw.text((70, 50 + row * 50), f'Certificate sample {row:02}  University course 2025', font=font, fill='black')
    return image


class ImageUprightTests(unittest.TestCase):
    def test_quarter_turns_preserve_all_pixels_and_orientation_sign(self):
        image = document()
        for rotation, transpose in [(90, Image.Transpose.ROTATE_270), (180, Image.Transpose.ROTATE_180), (270, Image.Transpose.ROTATE_90)]:
            with self.subTest(rotation=rotation):
                turned = image.transpose(transpose)
                result = apply_correction(turned, dict(rotation_degrees=rotation, deskew_degrees=0))
                self.assertEqual(result.size, image.size)
                self.assertEqual(result.tobytes(), image.tobytes())

    def test_projection_recovers_known_small_angle(self):
        for angle in [-8, -5, 5, 8]:
            with self.subTest(angle=angle):
                image = document().rotate(angle, expand=True, fillcolor='white')
                found, status = estimate_skew(image)
                self.assertEqual(status, 'deskew_applied')
                self.assertAlmostEqual(found, -angle, delta=.5)

    def test_upright_text_and_blank_image_are_not_deskewed(self):
        self.assertEqual(estimate_skew(document())[0], 0)
        self.assertEqual(estimate_skew(Image.new('RGB', (800, 600), 'white')), (0., 'insufficient_text'))
        with patch('ocr_app.image_preprocessing.classify_orientation') as classifier:
            image = Image.new('RGB', (400, 300), 'white')
            result, decision = prepare_image(image)
            self.assertIs(result, image)
            self.assertEqual(decision['status'], 'insufficient_text')
            classifier.assert_not_called()

    def test_disagreeing_views_abstain(self):
        with patch('ocr_app.image_preprocessing._session'), patch('ocr_app.image_preprocessing._classify_view', side_effect=[(90, .99, .9), (0, .98, .9)]):
            self.assertEqual(classify_orientation(document()), (0, 0., 0.))

    def test_low_score_or_margin_preserves_pixels(self):
        for prediction in [(90, .89, .8), (90, .99, .2)]:
            with self.subTest(prediction=prediction), patch('ocr_app.image_preprocessing.classify_orientation', return_value=prediction), patch('ocr_app.image_preprocessing.estimate_skew') as skew:
                image = document()
                result, decision = prepare_image(image)
                self.assertEqual(result.tobytes(), image.tobytes())
                self.assertEqual(decision['warning'], 'IMAGE_UPRIGHT_UNCERTAIN')
                skew.assert_not_called()

    def test_missing_or_invalid_model_degrades_without_failing_document(self):
        for error in [FileNotFoundError(), ValueError('bad model'), RuntimeError('bad runtime'), ImportError()]:
            with self.subTest(error=error), patch('ocr_app.image_preprocessing.classify_orientation', side_effect=error):
                image = document()
                result, decision = prepare_image(image)
                self.assertEqual(result.tobytes(), image.tobytes())
                self.assertEqual(decision['warning'], 'IMAGE_UPRIGHT_UNAVAILABLE')

    def test_deskew_expands_white_canvas_and_retains_corner_marks(self):
        image = document()
        draw = ImageDraw.Draw(image)
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255)]
        for x, y, color in zip([0, 780, 0, 780], [0, 0, 600, 600], colors):
            draw.rectangle((x, y, x + 19, y + 19), fill=color)
        result = apply_correction(image, dict(rotation_degrees=0, deskew_degrees=8))
        self.assertGreater(result.width, image.width)
        self.assertGreater(result.height, image.height)
        pixels = np.asarray(result)
        for color in colors:
            self.assertGreater(np.count_nonzero(np.all(pixels == color, axis=2)), 150)
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))

    def test_cancel_or_deadline_check_propagates_during_search(self):
        class Stopped(Exception):
            pass
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise Stopped()
        with patch('ocr_app.image_preprocessing.classify_orientation', return_value=(0, .99, .9)):
            with self.assertRaises(Stopped):
                prepare_image(document(), check)

    def test_expansion_above_pixel_limit_keeps_confirmed_right_angle_only(self):
        with patch('ocr_app.image_preprocessing.classify_orientation', return_value=(90, .99, .9)), patch('ocr_app.image_preprocessing.estimate_skew', return_value=(8., 'deskew_applied')), patch('ocr_app.image_preprocessing.MAX_CORRECTED_PIXELS', 500_000):
            result, decision = prepare_image(document())
        self.assertEqual(decision['rotation_degrees'], 90)
        self.assertEqual(decision['deskew_degrees'], 0)
        self.assertEqual(decision['warning'], 'IMAGE_DESKEW_UNCERTAIN')
        self.assertEqual(result.size, (620, 800))

    def test_exif_precedes_orientation_and_second_decode_reuses_exact_decision(self):
        image = document()
        stream = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        image.save(stream, format='JPEG', exif=exif)
        content = stream.getvalue()
        cache = {}
        with patch('ocr_app.image_preprocessing.classify_orientation', return_value=(90, .99, .9)) as classifier, patch('ocr_app.image_preprocessing.estimate_skew', return_value=(0., 'already_level')):
            first = next(decode_pages(content, preprocessing=cache))
            second = next(decode_pages(content, preprocessing=cache))
        classifier.assert_called_once()
        self.assertEqual(first.image.size, image.size)
        self.assertEqual(first.image.tobytes(), second.image.tobytes())
        self.assertEqual(first.ocr_boxes, [(0, 0, *image.size)])
        self.assertEqual(first.image_preprocessing, second.image_preprocessing)

    def test_pipeline_saves_and_recognizes_same_prepared_pixels(self):
        kinds = ['DIPLOMA', 'DEGREE_CERT', 'ID_CARD_FRONT', 'ID_CARD_BACK', 'BANK_CARD',
                 'BUSINESS_LICENSE', 'XUEXIN_DIPLOMA_TABLE', 'PASSPORT', 'HOUSEHOLD_REGISTER', 'MEDICAL_REPORT', 'INTERVIEW_FORM', 'GENERIC']
        upright = document()
        for kind in kinds:
            for rotation, transpose in [(90, Image.Transpose.ROTATE_270),
                                         (180, Image.Transpose.ROTATE_180),
                                         (270, Image.Transpose.ROTATE_90)]:
                with self.subTest(kind=kind, rotation=rotation):
                    saved, attempts, recognized = [], [], []
                    def recognize(model, encoded, task, timeout):
                        recognized.append(Image.open(io.BytesIO(base64.b64decode(encoded))).convert('RGB'))
                        return dict(text='姓名：测试甲\n学校名称：示例大学', termination_reason='eos')
                    def save(index, content, width, height):
                        saved.append(Image.open(io.BytesIO(content)).convert('RGB'))
                        self.assertEqual((width, height), upright.size)
                        return '9fd1a42b-95fd-4c78-b946-907f15b2093d'
                    with patch('ocr_app.image_preprocessing.classify_orientation', return_value=(rotation, .99, .9)) as classifier, patch('ocr_app.image_preprocessing.estimate_skew', return_value=(0., 'already_level')), patch('ocr_app.generic_layout.plan_form_regions', return_value=([dict(box=(0, 0, *upright.size), task='ocr', lines=[])], [])):
                        result = process_document(png_bytes(upright.transpose(transpose)), kind, recognize=recognize,
                            progress=lambda *args: None, save_page=save, record_attempt=attempts.append,
                            cancelled=lambda: False, deadline=time.monotonic() + 20)
                    self.assertEqual(result['status'], 'NEED_REVIEW')
                    classifier.assert_called_once()
                    self.assertEqual(saved[0].tobytes(), upright.tobytes())
                    self.assertEqual(saved[0].tobytes(), recognized[0].tobytes())
                    self.assertEqual(result['pages'][0]['image_preprocessing']['rotation_degrees'], rotation)
                    self.assertEqual(attempts[0]['image_preprocessing'], result['pages'][0]['image_preprocessing'])

    def test_bank_legacy_prediction_reuse_requires_unchanged_pixels(self):
        admission = dict(text='4111 1111 1111 1111', termination_reason='eos')
        for rotation, skew in [(0, 0), (90, 0), (0, 3)]:
            with self.subTest(rotation=rotation, skew=skew):
                recognize = Mock(return_value=dict(text='卡号 5555 5555 5555 4444', termination_reason='eos'))
                attempts = []
                with patch('ocr_app.image_preprocessing.classify_orientation', return_value=(rotation, .99, .9)), patch('ocr_app.image_preprocessing.estimate_skew', return_value=(skew, 'deskew_applied' if skew else 'already_level')):
                    result = process_document(png_bytes(document()), 'BANK_CARD', recognize=recognize,
                        options={'bank_admission': admission}, progress=lambda *args: None,
                        save_page=lambda *args: '9fd1a42b-95fd-4c78-b946-907f15b2093d',
                        record_attempt=attempts.append, cancelled=lambda: False, deadline=time.monotonic() + 20)
                changed = bool(rotation or skew)
                self.assertEqual(recognize.call_count, int(changed))
                self.assertEqual(len(attempts), int(changed))
                field = next(f for f in result['fields'] if f['key'] == 'card_number')
                self.assertEqual(field['value'], '5555555555554444' if changed else '4111111111111111')
                self.assertEqual(result['pages'][0]['extraction_method'], 'ocr')

    def test_bank_number_strip_skips_uncertain_rotation_and_still_recognizes(self):
        strip = Image.new('RGB', (1000, 70), 'white')
        ImageDraw.Draw(strip).text((5, 15), '4111 1111 1111 1111', fill='black')
        recognize = Mock(return_value=dict(text='4111 1111 1111 1111', termination_reason='eos'))
        with patch('ocr_app.image_preprocessing.classify_orientation') as classifier:
            result = process_document(png_bytes(strip), 'BANK_CARD', recognize=recognize,
                progress=lambda *args: None, save_page=lambda *args: '9fd1a42b-95fd-4c78-b946-907f15b2093d',
                record_attempt=lambda *args: None, cancelled=lambda: False, deadline=time.monotonic() + 20)
        classifier.assert_not_called()
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(result['pages'][0]['image_preprocessing']['status'], 'insufficient_text')
        self.assertEqual(next(f for f in result['fields'] if f['key'] == 'card_number')['value'], '4111111111111111')

    def test_scanned_pdf_decisions_are_cached_per_page_with_matching_preview(self):
        pdf = fitz.open()
        for im in [document(), document().transpose(Image.Transpose.ROTATE_90)]:
            page = pdf.new_page(width=im.width/2, height=im.height/2)
            page.insert_image(page.rect, stream=png_bytes(im))
        cache={'doc_type':'MEDICAL_REPORT'}
        with patch('ocr_app.image_preprocessing.classify_orientation',side_effect=[(90,.99,.9),(180,.99,.9)]) as classify, patch('ocr_app.image_preprocessing.estimate_skew',return_value=(0.,'already_level')):
            first=list(decode_pages(pdf.tobytes(),preprocessing=cache))
            second=list(decode_pages(pdf.tobytes(),preprocessing=cache))
        self.assertEqual(classify.call_count,2)
        self.assertEqual(set(cache['page_decisions']),{1,2})
        for before,after in zip(first,second):
            self.assertEqual(before.image.tobytes(),after.image.tobytes())
            self.assertEqual(before.ocr_boxes,[(0,0,*before.image.size)])
            self.assertFalse(before.evidence)
            self.assertEqual(before.image_preprocessing,after.image_preprocessing)

    def test_mixed_pdf_keeps_native_coordinates(self):
        pdf=fitz.open();page=pdf.new_page(width=400,height=500)
        page.insert_text((40,40),'Applicant information remains native and upright.')
        page.insert_image(fitz.Rect(40,100,300,400),stream=png_bytes(document()))
        before=next(decode_pages(pdf.tobytes()))
        with patch('ocr_app.image_preprocessing.prepare_image') as prepare:
            after=next(decode_pages(pdf.tobytes(),preprocessing={'doc_type':'INTERVIEW_FORM'}))
        prepare.assert_not_called()
        self.assertEqual(before.image.tobytes(),after.image.tobytes())
        self.assertEqual(before.ocr_boxes,after.ocr_boxes)
        self.assertEqual([b['bbox'] for b in before.evidence],[b['bbox'] for b in after.evidence])

    def test_native_pdf_paths_keep_existing_decoding(self):
        native = fitz.open()
        native.new_page().insert_text((50, 50), 'Native PDF text must remain unchanged.')
        content = native.tobytes()
        with patch('ocr_app.image_preprocessing.prepare_image') as prepare:
            page = next(decode_pages(content, preprocessing={}))
            self.assertTrue(page.evidence)
            self.assertIsNone(page.image_preprocessing)
            sources = [(kind, content) for kind in ['DIPLOMA', 'DEGREE_CERT', 'ID_CARD_FRONT',
                'ID_CARD_BACK', 'BANK_CARD', 'BUSINESS_LICENSE', 'XUEXIN_DIPLOMA_TABLE',
                'PASSPORT', 'HOUSEHOLD_REGISTER', 'MEDICAL_REPORT', 'GENERIC', 'INTERVIEW_FORM']]
            for kind, source in sources:
                process_document(source, kind, recognize=lambda *a: dict(text='测试文字', termination_reason='eos'),
                    progress=lambda *args: None, save_page=lambda *args: '9fd1a42b-95fd-4c78-b946-907f15b2093d',
                    record_attempt=lambda *args: None, cancelled=lambda: False, deadline=time.monotonic() + 20)
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
