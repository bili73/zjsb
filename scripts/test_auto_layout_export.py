"""Protect benchmark denominators and failed-attempt timing."""
import unittest
from export_auto_layout import summarize


class SummaryTests(unittest.TestCase):
    def test_failed_parent_stays_in_accuracy_and_timing(self):
        rows = [
            dict(model='paddleocr-vl', variant='automatic', cohort='difficult',
                 field_total=1, field_correct=1, complete_no_limit_or_repetition=1,
                 request_s=2.0, layout_preparation_s=.5),
            dict(model='paddleocr-vl', variant='automatic', cohort='difficult',
                 field_total=9, field_correct=0, complete_no_limit_or_repetition=0,
                 request_s=180.0, layout_preparation_s=.7),
        ]
        result = summarize(rows, 'paddleocr-vl', 'automatic', 'difficult')
        self.assertEqual(result['field_accuracy'], .1)
        self.assertEqual(result['ocr_request_s'], 182.0)
        self.assertEqual(result['complete_parents'], 1)
        self.assertEqual(result['parents'], 2)
        self.assertAlmostEqual(result['layout_preparation_s'], 1.2)

    def test_unscored_page_has_no_fabricated_accuracy(self):
        result = summarize([dict(model='glm-ocr', variant='automatic', cohort='control',
                                 field_total=0, field_correct=0,
                                 complete_no_limit_or_repetition=1, request_s=2.0)],
                           'glm-ocr', 'automatic', 'control')
        self.assertIsNone(result['field_accuracy'])
        self.assertEqual(result['ocr_request_s'], 2.0)


if __name__ == '__main__':
    unittest.main()
