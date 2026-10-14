import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.table_recognition import decode_table_output, locate_table_candidates, candidate_image, infer_header_rows


class PhotoTableRecognitionTests(unittest.TestCase):
    def test_header_inference_uses_tags_and_leaves_ambiguous_boundaries_unset(self):
        cases = [
            ('<tr><th>Name</th><th>Role</th></tr><tr><td>Alice</td><td>Admin</td></tr>', (1, 'model_tags')),
            ('<tr><th rowspan="2">Name</th><th colspan="2">Checks</th></tr><tr><th>A</th><th>B</th></tr><tr><td>X</td><td>Y</td><td>Z</td></tr>', (2, 'model_tags')),
            ('<tr><th>Name</th><td>Role</td></tr><tr><td>Alice</td><td>Admin</td></tr>', (None, None)),
            ('<tr><th rowspan="2">Name</th><th>Role</th></tr><tr><td>Admin</td></tr>', (None, None)),
            ('<tr><th>Name</th><th>Role</th></tr>', (None, None)),
            ('<tr><th colspan="2">Roster</th></tr><tr><td>Name</td><td>Role</td></tr><tr><td>Alice</td><td>Admin</td></tr>', (None, None)),
            ('<tr><th>Name</th></tr><tr><td>Alice</td><td>Admin</td></tr>', (None, None)),
        ]
        for html, expected in cases:
            with self.subTest(html=html):
                self.assertEqual(infer_header_rows(decode_table_output('<table>'+html+'</table>')[0]), expected)

    def test_structural_header_inference_preserves_matrix_and_merge_topology(self):
        import copy
        def merge(row, column, rowspan, colspan):
            return dict(row=row, column=column, rowspan=rowspan, colspan=colspan)
        cases = [
            ([['序号','名称','备注'],['1','甲',''],['2','乙','']], [], (1,'structure')),
            ([['品名','数量','价格'],['甲','2','3.5'],['乙','4','6.8']], [], (1,'structure')),
            ([['序号','测量',''],['','甲','乙'],['1','2','3'],['2','4','5']], [merge(0,0,2,1),merge(0,1,1,2)], (2,'structure')),
            ([['序号','测量','',''],['','甲','','乙'],['','早','晚',''],['1','2','3','4'],['2','5','6','7']], [merge(0,0,3,1),merge(0,1,1,3),merge(1,1,1,2),merge(1,3,2,1)], (3,'structure')),
            ([['1','甲','3.5'],['2','乙','4.6'],['3','丙','5.7']], [], (0,'data_rows')),
            ([['姓名','部门'],['甲','一部'],['乙','二部']], [], (None,None)),
            ([['1','甲'],['2','乙'],['3','丙']], [], (None,None)),
            ([['年份','2024','2025'],['甲','1','2'],['乙','3','4']], [], (None,None)),
            ([['2023','2024'],['1','2'],['2','3']], [], (None,None)),
            ([['1','2'],['2','3'],['3','4']], [], (None,None)),
            ([['统计表','',''],['序号','姓名','年龄'],['1','甲','20'],['2','乙','21']], [merge(0,0,1,3)], (None,None)),
            ([['序号','组别','结果'],['1','','3'],['2','乙','4']], [merge(0,1,2,1)], (None,None)),
            ([['备注','',''],['序号','姓名','年龄'],['1','甲','20'],['2','乙','21']], [], (None,None)),
            ([['序号','姓名'],['1','甲']], [], (None,None)),
        ]
        for rows, merges, expected in cases:
            original=dict(rows=rows,merges=merges,header_rows=None,warnings=[])
            before=copy.deepcopy(original)
            with self.subTest(rows=rows[:3]):
                self.assertEqual(infer_header_rows(original), expected)
                self.assertEqual(original,before)

    def test_otsl_blanks_repeats_and_leading_zero_remain_in_place(self):
        result = decode_table_output('<fcel>A<fcel>A<ecel><nl><fcel>001<ecel><fcel>=SUM(A1)<nl>')[0]
        self.assertEqual(result['rows'], [['A', 'A', ''], ['001', '', '=SUM(A1)']])
        self.assertIsNone(result['header_rows'])

    def test_explicit_multirow_headers_and_spans(self):
        result = decode_table_output('<table><tr><th rowspan="2">Name</th><th colspan="2">Checks</th></tr><tr><th>A</th><th>B</th></tr><tr><td>X</td><td></td><td>Y<br>Z</td></tr></table>')[0]
        self.assertEqual(result['header_rows'], 2)
        self.assertEqual(result['rows'], [['Name','Checks',''],['','A','B'],['X','','Y\nZ']])
        self.assertEqual(len(result['merges']), 2)

    def test_invalid_and_truncated_tables_are_not_repaired_silently(self):
        for raw in ['hello', '<table><tr><td>A</td></tr>', '<table><tr><td>A</tr></table>',
                    '<table><tr><td rowspan="2">A</td></tr></table>',
                    '<table><tr><td colspan="201">A</td></tr></table>',
                    '<table><table></table></table>']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_table_output(raw)

    def test_two_tables_and_ragged_rows_survive(self):
        results = decode_table_output('<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table><table><tr><td>D</td></tr></table>')
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['rows'], [['A',''],['B','C']])
        self.assertIn('TABLE_RAGGED_ROWS', results[0]['warnings'])

    def test_locator_prefers_dense_grid_to_notice_and_keeps_original(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (800, 800), 'white')
        draw = ImageDraw.Draw(image)
        for x in [40, 150, 760]:
            draw.line((x, 30, x, 220), fill='black', width=2)
        for y in [30, 100, 220]:
            draw.line((40,y,760,y), fill='black', width=2)
        for x in range(40, 761, 80):
            draw.line((x, 300, x, 700), fill='black', width=2)
        for y in range(300, 701, 50):
            draw.line((40,y,760,y), fill='black', width=2)
        before = image.tobytes()
        candidates = locate_table_candidates(image)
        self.assertGreaterEqual(len(candidates), 2)
        self.assertGreater(candidates[0]['box'][1], 250)
        crop, transform = candidate_image(image, candidates[0])
        self.assertEqual(image.tobytes(), before)
        self.assertGreater(crop.width, crop.height)
        self.assertIsNotNone(transform)
        from ocr_app.table_recognition import grid_dimensions_hint
        self.assertEqual(grid_dimensions_hint(crop),[8,9])


if __name__ == '__main__':
    unittest.main()
