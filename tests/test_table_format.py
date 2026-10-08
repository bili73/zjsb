import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_medical_items
from ocr_app.table_format import table_html


class TableFormatTests(unittest.TestCase):
    def test_medical_result_stays_in_its_column_with_span_and_marker(self):
        text = ('<fcel>合成血常规<lcel><lcel><lcel><nl>'
                '<fcel>项目<fcel>结果<fcel>单位<fcel>参考范围<nl>'
                '<fcel>WBC<fcel>12.3↑<fcel>10^9/L<fcel>3.5-9.5<nl>')
        items, limitations = extract_medical_items([dict(text=text, page=1, extraction_method='ocr')])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['result_raw'], '12.3↑')
        self.assertEqual(items[0]['unit'], '10^9/L')
        self.assertEqual(items[0]['reference_range'], '3.5-9.5')
        self.assertEqual(items[0]['abnormal_flag'], 'HIGH')
        self.assertIsNone(items[0]['confidence'])
        self.assertTrue(items[0]['need_review'])
        self.assertEqual(limitations, [])

    def test_two_dimensional_span_and_html_escaping(self):
        rendered = table_html('<fcel><script>&<lcel><fcel>R<nl><ucel><xcel><fcel>S<nl>')
        self.assertIn('rowspan="2" colspan="2"', rendered)
        self.assertIn('&lt;script&gt;&amp;', rendered)
        self.assertNotIn('<script>', rendered)

    def test_ragged_rows_pad_empty_without_dropping_content(self):
        rendered = table_html('<fcel>A<nl><fcel>B<fcel>C<nl>')
        self.assertEqual(rendered, '<table><tr><td>A</td><td></td></tr><tr><td>B</td><td>C</td></tr></table>')

    def test_orphan_and_non_rectangular_spans_are_not_guessed(self):
        for text in ['<fcel>A<nl><lcel><nl>',
                     '<fcel>A<lcel><nl><ucel><fcel>B<nl>',
                     '<ecel>unexpected<nl>', '<fcel>A<nl>unexpected']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    table_html(text)
        items, limitations = extract_medical_items([dict(text='<fcel>A<nl><lcel><nl>', page=1)])
        self.assertEqual(items, [])
        self.assertTrue(any('OTSL' in message for message in limitations))

    def test_existing_html_and_plain_text_are_preserved(self):
        for text in ['plain text', '<table><tr><td>WBC</td></tr></table>']:
            self.assertEqual(table_html(text), text)


if __name__ == '__main__':
    unittest.main()
