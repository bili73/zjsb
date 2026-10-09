"""Regression for the user's printed study-interval date convention."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_fields

def fields(*texts):
    return {f['key']: f for f in extract_fields([
        dict(text=t, page=i+1, extraction_method='ocr') for i, t in enumerate(texts)], 'DIPLOMA')}

class DiplomaMappingRepairTests(unittest.TestCase):
    def test_interval_start_end_and_footer_have_separate_roles(self):
        result = fields('于2021年9月1日至2025年6月30日在本校测试专业学习。\n证书编号：0000123\n2025年7月2日')
        self.assertEqual(result['enroll_date']['value'], '2021-09-01')
        self.assertEqual(result['graduate_date']['value'], '2025-06-30')
        self.assertEqual(result['issue_date']['value'], '2025-07-02')
        self.assertIn('2025年6月30日', result['graduate_date']['source']['raw_text'])

    def test_chinese_O_year_and_month_precision_do_not_change_identifiers(self):
        result = fields('于二O二一\n年九月至二〇二五年六月在本学院物流管理专业学习。\n证书编号：00O123 二O二五年七月三日')
        self.assertEqual(result['enroll_date']['value'], '2021-09')
        self.assertEqual(result['graduate_date']['value'], '2025-06')
        self.assertEqual(result['issue_date']['value'], '2025-07-03')
        self.assertEqual(result['certificate_no']['value'], '00O123')
        self.assertEqual(result['major']['value'], '物流管理')

    def test_footer_alone_never_supplies_graduation(self):
        result = fields('证书编号：000123 2025年6月19日')
        self.assertEqual(result['issue_date']['value'], '2025-06-19')
        self.assertIsNone(result['graduate_date']['value'])

    def test_labelled_school_delimited_by_dean(self):
        result = fields('校 名：示例大学城市学院 院 长：测试人员')
        self.assertEqual(result['school_name']['value'], '示例大学城市学院')
        self.assertNotIn('principal', result)

    def test_explicit_school_beats_cover_but_equivalent_labels_conflict(self):
        result = fields('错读师范学院\n毕业证书', '校名：示例师范学院')
        self.assertEqual(result['school_name']['value'], '示例师范学院')
        conflict = fields('校名：示例师范学院', '学校名称：另一师范学院')
        self.assertIsNone(conflict['school_name']['value'])
        self.assertEqual(conflict['school_name']['review_reason'], 'CONFLICT')

    def test_invalid_reverse_and_conflicting_intervals_are_not_selected(self):
        for text in ['于2025年9月至2021年6月在本校学习。', '于2021年9月至2025年2月30日在本校学习。']:
            with self.subTest(text=text):
                self.assertIsNone(fields(text)['graduate_date']['value'])
        result = fields('于2021年9月至2025年6月在本校学习。\n毕业日期：2025年7月')
        self.assertIsNone(result['graduate_date']['value'])
        self.assertEqual(result['graduate_date']['review_reason'], 'CONFLICT')

if __name__ == '__main__':
    unittest.main()
