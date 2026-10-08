"""CPU regression tests for native, header-guided medical table recovery."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import fitz
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.documents import decode_pages, reliable_text


def sample_pdf(groups=None, headers=None, ruled=False):
    document = fitz.open()
    page = document.new_page(width=540, height=700)
    bounds = [40, 90, 220, 280, 350, 500]
    groups = groups or [(50, [1, 2, 3])]
    headers = headers or ['序号', '检验项目', '缩写', '检测结果', '参考范围']
    for top, numbers in groups:
        page.draw_rect(fitz.Rect(bounds[0], top, bounds[-1], top + 30))
        for x in bounds[1:-1]:
            page.draw_line((x, top), (x, top + 30))
        for x, text in zip(bounds, headers):
            page.insert_text((x+4, top+20), text, fontname='china-s', fontsize=10)
        for i, number in enumerate(numbers):
            baseline = top + 50 + i * 25
            for x, value in zip(bounds, [str(number), '测试项目', f'T{i+1}', f'{i+1}.00', '0-9']):
                page.insert_text((x+4, baseline), value, fontname='china-s', fontsize=10)
            if ruled:
                page.draw_line((bounds[0], baseline+6), (bounds[-1], baseline+6))
        if ruled:
            for x in bounds:
                page.draw_line((x, top+30), (x, top+56+(len(numbers)-1)*25))
        page.insert_text((285, top+70+len(numbers)*25), '审核签名', fontname='china-s', fontsize=10)
    return document.tobytes()


def prepared(data):
    with contextlib.redirect_stdout(io.StringIO()):
        return list(decode_pages(data))[0]


def table_blocks(page):
    return [b for b in page.evidence if b['text'].startswith('<table>')]


def numbered_rows(block):
    result = []
    for tr in BeautifulSoup(block['text'], 'html.parser').find_all('tr'):
        cells = [c.get_text() for c in tr.find_all(['td', 'th'])]
        if cells and cells[0].strip().isdigit():
            result.append(cells)
    return result


class NativeMedicalTablesTests(unittest.TestCase):
    def test_header_only_grid_recovers_unruled_body_and_excludes_footer(self):
        page = prepared(sample_pdf())
        blocks = table_blocks(page)
        rows = [row for block in blocks for row in numbered_rows(block)]
        self.assertEqual([row[0] for row in rows], ['1', '2', '3'])
        self.assertEqual([row[3] for row in rows], ['1.00', '2.00', '3.00'])
        self.assertNotIn('审核签名', ''.join(block['text'] for block in blocks))
        self.assertEqual(blocks[0]['table_recovery'], 'header_guided_text')

    def test_row_and_cell_geometry_matches_html_and_whole_page(self):
        block = table_blocks(prepared(sample_pdf()))[0]
        self.assertEqual(len(block['table_rows']), len(BeautifulSoup(block['text'], 'html.parser').find_all('tr')))
        for row in block['table_rows']:
            self.assertEqual(len(row['cell_bboxes']), 5)
            for box in [row['bbox']] + row['cell_bboxes']:
                self.assertIsNotNone(box)
                self.assertTrue(all(0 <= coordinate <= 1 for coordinate in box))
                self.assertLess(box[0], box[2])
                self.assertLess(box[1], box[3])
        self.assertTrue(block['table_rows'][0]['is_header'])
        self.assertTrue(all(not row['is_header'] for row in block['table_rows'][1:]))

    def test_multiple_tables_have_separate_bodies(self):
        page = prepared(sample_pdf(groups=[(50, [1, 2]), (300, [1, 2, 3, 4])]))
        self.assertEqual([[r[0] for r in numbered_rows(b)] for b in table_blocks(page)],
                         [['1', '2'], ['1', '2', '3', '4']])

    def test_no_fixed_row_limit_or_start_number(self):
        page = prepared(sample_pdf(groups=[(50, list(range(31, 38)))]))
        self.assertEqual([int(r[0]) for r in numbered_rows(table_blocks(page)[0])], list(range(31, 38)))

    def test_sequence_gaps_and_duplicates_are_not_silently_recovered(self):
        for sequence in [[1, 3], [1, 1], [3, 2]]:
            with self.subTest(sequence=sequence):
                page = prepared(sample_pdf(groups=[(50, sequence)]))
                self.assertEqual([r for b in table_blocks(page) for r in numbered_rows(b)], [])
                self.assertTrue(page.limitations)

    def test_missing_or_ambiguous_headers_do_not_guess_columns(self):
        for headers in [['序号', '说明', '缩写', '检测结果', '参考范围'],
                        ['序号', '检验项目', '检测结果', '检测结果', '参考范围']]:
            with self.subTest(headers=headers):
                page = prepared(sample_pdf(headers=headers))
                self.assertEqual([r for b in table_blocks(page) for r in numbered_rows(b)], [])

    def test_existing_fully_ruled_path_stays_native(self):
        blocks = table_blocks(prepared(sample_pdf(ruled=True)))
        self.assertEqual(len(numbered_rows(blocks[0])), 3)
        self.assertEqual(blocks[0]['table_recovery'], 'native_lines')

    def test_recovery_library_failure_keeps_original_header_evidence(self):
        with patch('ocr_app.documents._recover_header_body', side_effect=ValueError('fixture')):
            page = prepared(sample_pdf())
        blocks = table_blocks(page)
        self.assertEqual(len(blocks), 1)
        self.assertIn('检验项目', blocks[0]['text'])
        self.assertEqual(blocks[0]['table_recovery'], 'native_lines')
        self.assertTrue(page.limitations)

    def test_known_bullet_only_at_list_position_is_allowed(self):
        self.assertTrue(reliable_text('\uf076 这是一个简短结论。'))
        self.assertTrue(reliable_text('标题说明\n  \uf076 这是简短结论。'))
        self.assertFalse(reliable_text('这是\uf076一个简短结论。'))
        self.assertFalse(reliable_text('\ue001 这是一个简短结论。'))
        self.assertFalse(reliable_text('\uf076\ue001 简短结论内容。'))


if __name__ == '__main__':
    unittest.main()
