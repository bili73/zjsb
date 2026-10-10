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

    def test_partial_number_labels_preserve_value_source_and_footer(self):
        for label in ('书编号', '编号', '书 编 号', '编 号'):
            with self.subTest(label=label):
                result = fields(f'{label}：00O123 2025年7月2日')
                number = result['certificate_no']
                self.assertEqual(number['value'], '00O123')
                self.assertIn(label, number['source']['raw_text'])
                self.assertEqual(number['source']['page'], 1)
                self.assertIsNone(number['confidence'])
                self.assertTrue(number['need_review'])
                self.assertEqual(result['issue_date']['value'], '2025-07-02')
                self.assertIsNone(result['graduate_date']['value'])

    def test_partial_number_labels_support_wrapped_and_table_values(self):
        for text in ('书编号：\n000123', '编号 000123',
                     '<table><tr><td>编号</td><td>000123</td><td>校名</td><td>示例大学</td></tr></table>'):
            with self.subTest(text=text):
                self.assertEqual(fields(text)['certificate_no']['value'], '000123')
        result = fields('编号：000123\n二〇二五年七月二日')
        self.assertEqual(result['issue_date']['value'], '2025-07-02')

    def test_number_aliases_do_not_match_unrelated_compound_labels(self):
        for label in ('身份证编号', '档案编号', '学生编号', '报告编号', '图书编号', '证书编号码'):
            with self.subTest(label=label):
                result = fields(f'{label}：000123\n2025年7月2日')
                self.assertIsNone(result['certificate_no']['value'])
                self.assertIsNone(result['issue_date']['value'])

    def test_partial_number_candidates_preserve_conflict_and_deduplicate(self):
        result = fields('证书编号：000123', '书编号：000123', '编号：000123')
        self.assertEqual(result['certificate_no']['value'], '000123')
        for text in ('书编号：000124', '编号：000124'):
            with self.subTest(text=text):
                number = fields('证书编号：000123', text)['certificate_no']
                self.assertIsNone(number['value'])
                self.assertEqual(number['review_reason'], 'CONFLICT')
                self.assertEqual({c['value'] for c in number['candidates']}, {'000123', '000124'})

    def test_partial_number_labels_do_not_guess_obscured_digits(self):
        for value in ('000123****', '000123 ****', '000123 456789', '000123 未知说明', '****', 'ABC'):
            with self.subTest(value=value):
                number = fields(f'编号：{value}')['certificate_no']
                self.assertIsNone(number['value'])
                self.assertEqual(number['review_reason'], 'MISSING')

    def test_partial_number_aliases_do_not_expand_degree_profile(self):
        for label in ('书编号', '编号'):
            with self.subTest(label=label):
                result = {f['key']: f for f in extract_fields([
                    dict(text=f'{label}：000123\n2025年7月2日', page=1, extraction_method='ocr')], 'DEGREE_CERT')}
                self.assertIsNone(result['certificate_no']['value'])
                self.assertIsNone(result['award_date']['value'])

    def test_decimal_duration_and_wrapped_curriculum_level(self):
        result = fields('专业，业余 学习，修完 2.5年制 专\n科教学计划规定的全部课程，成绩合格，准予毕业。')
        self.assertEqual(result['duration']['value'], '2.5年')
        self.assertEqual(result['duration']['source']['raw_text'], '2.5年制')
        self.assertEqual(result['education_level']['value'], '专科')
        self.assertIn('专\n科教学计划', result['education_level']['source']['raw_text'])

    def test_integer_and_decimal_durations_preserve_printed_precision(self):
        for printed, expected in (('2.5', '2.5年'), ('2.50', '2.50年'), ('3', '3年'), ('三', '三年')):
            with self.subTest(printed=printed):
                result = fields(f'修完 {printed} 年 制规定的全部课程。')
                self.assertEqual(result['duration']['value'], expected)
                self.assertEqual(result['duration']['source']['raw_text'], f'{printed} 年 制')

    def test_malformed_decimals_never_supply_an_integer_suffix(self):
        for printed in ('.5', '2..5', '2.5.5', '2．5', '2.5．5'):
            with self.subTest(printed=printed):
                self.assertIsNone(fields(f'修完 {printed}年制规定课程。')['duration']['value'])

    def test_curriculum_levels_accept_wrapping_and_keep_conflicts(self):
        for printed, expected in (('专\n科', '专科'), ('本 科', '本科'), ('研 究 生', '研究生')):
            with self.subTest(printed=printed):
                self.assertEqual(fields(f'{printed} 教 学 计 划规定的全部课程。')['education_level']['value'], expected)
        for key, text in (('duration', '学制：3年\n修完2.5年制规定课程。'),
                          ('education_level', '学历层次：本科\n专科教学计划规定的全部课程。')):
            with self.subTest(key=key):
                field = fields(text)[key]
                self.assertIsNone(field['value'])
                self.assertEqual(field['review_reason'], 'CONFLICT')

    def test_duration_and_level_are_not_inferred_from_unrelated_context(self):
        result = fields('本科学历招生咨询\n专科学校简介\n于2017年3月至2019年7月在本校学习。')
        self.assertIsNone(result['duration']['value'])
        self.assertIsNone(result['education_level']['value'])

    def test_missing_day_glyph_is_tolerated_only_for_issuance(self):
        for date in ('二〇二六年 七 月 二', '2026年7月2'):
            with self.subTest(date=date):
                result = fields(f'书编号：000123\n{date}')
                self.assertEqual(result['issue_date']['value'], '2026-07-02')
                self.assertIn(date.strip(), result['issue_date']['source']['raw_text'])
                self.assertIsNone(result['graduate_date']['value'])
                inline = fields(f'编号：000123 {date} 查询：说明')
                self.assertEqual(inline['certificate_no']['value'], '000123')
                self.assertEqual(inline['issue_date']['value'], '2026-07-02')
                self.assertEqual(fields(f'发证日期：{date}')['issue_date']['value'], '2026-07-02')

    def test_missing_day_glyph_does_not_guess_masked_or_invalid_days(self):
        for date in ('2026年2月30', '2026年7月32', '2026年7月0', '2026年7月二*', '2026年7月2 未知说明'):
            with self.subTest(date=date):
                self.assertIsNone(fields(f'编号：000123\n{date}')['issue_date']['value'])
        self.assertEqual(fields('编号：000123\n2026年7月')['issue_date']['value'], '2026-07')
        self.assertIsNone(fields('2026年7月2')['issue_date']['value'])
        conflict = fields('编号：000123\n2026年7月2\n2026年7月3日')['issue_date']
        self.assertIsNone(conflict['value'])
        self.assertEqual(conflict['review_reason'], 'CONFLICT')

    def test_missing_day_glyph_does_not_expand_other_date_fields_or_degree(self):
        for key, label in (('birth_date', '出生日期'), ('enroll_date', '入学日期'), ('graduate_date', '毕业日期')):
            with self.subTest(key=key):
                self.assertIsNone(fields(f'{label}：2026年7月2')[key]['value'])
        result = {f['key']: f for f in extract_fields([
            dict(text='证书编号：000123\n2026年7月2', page=1, extraction_method='ocr')], 'DEGREE_CERT')}
        self.assertIsNone(result['award_date']['value'])

if __name__ == '__main__':
    unittest.main()
