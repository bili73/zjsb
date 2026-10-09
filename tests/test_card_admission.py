"""Photo admission is decoder-only; each card is recognized in its own task."""
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.business import prepare_uploads
from ocr_app.pipeline import process_document
from ocr_app.task_store import TaskError


def image_bytes(size=(850, 540)):
    stream = io.BytesIO()
    Image.new('RGB', size, 'white').save(stream, format='PNG')
    return stream.getvalue()


def run_card(text, options=None):
    recognize = Mock(return_value=dict(text=text, termination_reason='eos'))
    result = process_document(image_bytes(), 'BANK_CARD', recognize=recognize,
                              progress=lambda *args: None, save_page=lambda *args: 'synthetic-page',
                              record_attempt=lambda *args: None, cancelled=lambda: False,
                              deadline=time.monotonic() + 10, options=options)
    return result, recognize


class CardAdmissionTests(unittest.TestCase):
    def test_full_face_and_row_are_accepted_without_recognition(self):
        runtime = Mock()
        for size in [(850, 540), (800, 100), (540, 850)]:
            raw = image_bytes(size)
            file = prepare_uploads([(raw, 'card.png')], 'BANK_CARD', runtime)[0]
            self.assertEqual(file['data'], raw)
            self.assertEqual(file['actual_source_page_count'], 1)
            self.assertNotIn('admission', file)
        runtime.request.assert_not_called()

    def test_pdf_and_malformed_photo_are_rejected_before_storage(self):
        import fitz
        with fitz.open() as document:
            document.new_page()
            pdf = document.tobytes()
        runtime = Mock()
        for data, code in [(pdf, 'UNSUPPORTED_FORMAT'), (b'not an image', 'DECODE_FAILED')]:
            with self.subTest(code=code), self.assertRaises(TaskError) as caught:
                prepare_uploads([(data, 'card.png')], 'BANK_CARD', runtime)
            self.assertEqual(caught.exception.code, code)
        runtime.request.assert_not_called()

    def test_batch_does_not_wait_for_model_readiness_or_readable_pan(self):
        runtime = Mock()
        runtime.request.side_effect = AssertionError('Model is unavailable')
        files = prepare_uploads([(image_bytes(), f'card-{i}.png') for i in range(20)], 'BANK_CARD', runtime)
        self.assertEqual(len(files), 20)
        runtime.request.assert_not_called()

    def test_other_document_uploads_remain_decoder_only(self):
        runtime = Mock()
        files = prepare_uploads([(image_bytes(), 'synthetic.png')], 'ID_CARD_FRONT', runtime)
        self.assertEqual(files[0]['actual_source_page_count'], 1)
        self.assertNotIn('admission', files[0])
        runtime.request.assert_not_called()

    def test_full_face_background_ocr_extracts_pan_from_mixed_text(self):
        raw = '合成银行\n借记卡\n卡号 ４１１１ １１１１ １１１１ １１１１\n有效期 12/28\n服务热线 95588'
        result, recognize = run_card(raw)
        field = next(f for f in result['fields'] if f['key'] == 'card_number')
        self.assertEqual(field['value'], '4111111111111111')
        self.assertEqual(field['source']['raw_text'], '４１１１ １１１１ １１１１ １１１１')
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertEqual(result['pages'][0]['extraction_method'], 'ocr')
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(recognize.call_args.args[0], 'glm_ocr')

    def test_unreadable_card_does_not_reject_the_other_card(self):
        first, _ = run_card('卡号无法读出')
        second, _ = run_card('卡号 4111 1111 1111 1111')
        missing = next(f for f in first['fields'] if f['key'] == 'card_number')
        value = next(f for f in second['fields'] if f['key'] == 'card_number')
        self.assertEqual(first['status'], 'NEED_REVIEW')
        self.assertIsNone(missing['value'])
        self.assertTrue(missing['need_review'])
        self.assertNotIn('error', first)
        self.assertEqual(value['value'], '4111111111111111')

    def test_legacy_admission_reuses_prediction_without_second_recognition(self):
        admission = dict(text='4111 1111 1111 1111', normalized='4111111111111111', termination_reason='eos')
        result, recognize = run_card('must not be used', {'bank_admission': admission})
        recognize.assert_not_called()
        self.assertEqual(next(f for f in result['fields'] if f['key'] == 'card_number')['value'], '4111111111111111')

    def test_incomplete_legacy_admission_falls_back_to_background_ocr(self):
        result, recognize = run_card('4111 1111 1111 1111', {'bank_admission': {'termination_reason': 'token_limit'}})
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(result['status'], 'NEED_REVIEW')


if __name__ == '__main__':
    unittest.main()
