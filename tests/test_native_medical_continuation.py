"""Source geometry, not a declared abnormal count, governs PDF continuation."""
from pathlib import Path
import sys
import unittest
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.documents import decode_pages
from ocr_app.extraction import extract_medical_items

def sample(*, shifted=False, numbers=(1, 2), blank_between=False, another_table=True, next_width=540):
    doc = fitz.open()
    bounds = [30, 70, 180, 220, 300, 365, 420, 480, 515]
    def header(page, top, labels, xs=bounds):
        page.draw_rect(fitz.Rect(xs[0], top, xs[-1], top+28))
        for x in xs[1:-1]:
            page.draw_line((x, top), (x, top+28))
        for x, value in zip(xs, labels):
            page.insert_text((x+3, top+18), value, fontname='china-s', fontsize=8)
    labels = ['序号', '检验项目', '缩写', '检测方法学', '检测结果', '单位', '参考范围', '风险']
    header(doc.new_page(width=540, height=700), 635, labels)
    if blank_between:
        doc.new_page(width=540, height=700).insert_text((40,50), '独立说明页面', fontname='china-s')
    page = doc.new_page(width=next_width, height=700)
    xs = [x+12 for x in bounds] if shifted else bounds
    header(page, 40, ['']*7 + ['等级'], xs)
    for index, number in enumerate(numbers):
        values = [str(number), '潜血' if index == 0 else '蛋白质', 'BLD' if index == 0 else 'PRO',
                  '干化学法', '+3' if index == 0 else '+1', 'u', '/', 'E3']
        for x, value in zip(xs, values):
            page.insert_text((x+3, 87+index*25), value, fontname='china-s', fontsize=8)
    page.insert_text((30,170), '标本接收时间：2026-03-11', fontname='china-s', fontsize=8)
    if another_table:
        header(page, 250, labels[:-1]+['风险等级'])
        for x,value in zip(bounds,['1','另一指标','OTHER','测试法','4','u','0-9','A']):
            page.insert_text((x+3,295),value,fontname='china-s',fontsize=8)
    return doc.tobytes()

class NativeMedicalContinuationTests(unittest.TestCase):
    def items(self, data):
        pages=list(decode_pages(data))
        items, _ = extract_medical_items([b for p in pages for b in p.evidence])
        return pages, items

    def test_split_header_recovers_results_grades_and_actual_page_sources(self):
        pages, items=self.items(sample())
        by_name={i['name']:i for i in items}
        self.assertEqual(set(by_name), {'潜血','蛋白质','另一指标'})
        for name,value in [('潜血','+3'),('蛋白质','+1')]:
            self.assertEqual(by_name[name]['result_raw'],value)
            self.assertEqual(by_name[name]['risk_grade'],'E3')
            self.assertEqual(by_name[name]['source']['page'],2)
            self.assertEqual(by_name[name]['source']['bbox_kind'],'row')
        continued=next(b for b in pages[1].evidence if b.get('table_recovery')=='split_header_continuation')
        self.assertEqual(continued['table_header_source']['page'],1)
        self.assertNotIn('标本接收时间',continued['text'])
        self.assertNotIn('另一指标',continued['text'])
        self.assertFalse(any('没有可靠恢复' in reason for p in pages for reason in p.limitations))

    def test_changed_column_geometry_is_not_inherited(self):
        pages,items=self.items(sample(shifted=True))
        self.assertNotIn('潜血',{i['name'] for i in items})
        self.assertTrue(any(p.limitations for p in pages))

    def test_sequence_conflict_rejects_body_and_preserves_evidence(self):
        for numbers in [(1,3),(1,1),(3,2)]:
            with self.subTest(numbers=numbers):
                pages,items=self.items(sample(numbers=numbers))
                self.assertNotIn('潜血',{i['name'] for i in items})
                self.assertTrue(any('潜血' in b['text'] for p in pages for b in p.evidence))
                self.assertTrue(any(p.limitations for p in pages))

    def test_header_is_never_carried_over_an_intervening_page(self):
        _,items=self.items(sample(blank_between=True))
        self.assertNotIn('潜血',{i['name'] for i in items})

    def test_changed_page_size_rejects_inheritance(self):
        pages,items=self.items(sample(next_width=560))
        self.assertNotIn('潜血',{i['name'] for i in items})
        self.assertTrue(any(p.limitations for p in pages))

    def test_unresolved_final_header_is_reported(self):
        doc=fitz.open(stream=sample(another_table=False), filetype='pdf')
        doc.delete_page(1)
        pages,_=self.items(doc.tobytes())
        self.assertTrue(pages[0].limitations)

if __name__=='__main__':
    unittest.main()
