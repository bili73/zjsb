"""Degree footer recovery stays bound to observed school and date context."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_fields


def fields(*texts, kind='DEGREE_CERT'):
    return {f['key']: f for f in extract_fields([
        dict(text=text, page=i + 1, extraction_method='ocr') for i, text in enumerate(texts)], kind)}


class DegreeMappingRepairTests(unittest.TestCase):
    def test_misread_heading_does_not_discard_signing_school_or_punctuated_date(self):
        text = ('错读师范学院\n学士学位证书\n'
                '学生 测试甲 性别 女，2003年10月27日生。\n'
                '在本校测试专业完成了本科学习计划，授予管理学学士学位。\n'
                '示例师范学院\n院 长\n学位评定委员会主席\n'
                '证书编号：00O123\n（二O二五年 六月 十九 日\n（普通高等教育本科毕业生）')
        result = fields(text)
        self.assertEqual(result['school_name']['value'], '示例师范学院')
        self.assertIn('院 长', result['school_name']['source']['raw_text'])
        self.assertEqual(result['award_date']['value'], '2025-06-19')
        self.assertIn('（二O二五年', result['award_date']['source']['raw_text'])
        self.assertEqual(result['birth_date']['value'], '2003-10-27')
        self.assertEqual(result['certificate_no']['value'], '00O123')
        self.assertIsNone(result['school_name']['confidence'])
        self.assertTrue(result['school_name']['need_review'])

    def test_signature_boundaries_and_spaced_school_are_shared(self):
        for kind in ('DIPLOMA', 'DEGREE_CERT'):
            for title in ('院 长', '校 长', '校（院）长', '学位评定委员会主席'):
                with self.subTest(kind=kind, title=title):
                    result = fields(f'学校名称：示 例 大 学 {title}：测试乙', kind=kind)
                    self.assertEqual(result['school_name']['value'], '示例大学')
                    self.assertNotIn('principal', result)

    def test_explicit_diploma_school_not_shadowed_by_network_school_narrative(self):
        result = fields('于2021年9月至2025年6月在本校网络教育学院测试专业学习。\n'
                        '校 名：示例大学 校 长：测试乙', kind='DIPLOMA')
        self.assertEqual(result['school_name']['value'], '示例大学')
        self.assertEqual(result['school_name']['source']['raw_text'], '校 名：示例大学')

    def test_signing_school_outranks_heading_and_narrative(self):
        for separator in (' ', '\n', '\n\n'):
            for title in ('校 长', '院长', '学位评定委员会主席'):
                with self.subTest(separator=separator, title=title):
                    result = fields('错读学院\n在另一大学测试专业学习。\n'
                                    f'示 例 大 学{separator}{title}：测试乙')
                    self.assertEqual(result['school_name']['value'], '示例大学')

    def test_explicit_and_signing_schools_have_equal_authority(self):
        result = fields('学校名称：示例大学\n另一大学\n校长：测试乙')
        self.assertIsNone(result['school_name']['value'])
        self.assertEqual(result['school_name']['review_reason'], 'CONFLICT')
        result = fields('示例大学\n校长：测试乙', '另一大学\n院长：测试丙')
        self.assertIsNone(result['school_name']['value'])
        self.assertEqual(result['school_name']['review_reason'], 'CONFLICT')
        self.assertEqual(fields('学校名称：示例大学\n示例大学\n校长：测试乙')['school_name']['value'], '示例大学')

    def test_bare_school_conflicts_and_unrelated_titles_stay_unresolved(self):
        for text in ('示例大学\n另一大学', '示例大学\n另一大学\n院长致辞',
                     '示例大学\n另一大学\n专业说明\n校长：测试乙'):
            with self.subTest(text=text):
                result = fields(text)
                self.assertIsNone(result['school_name']['value'])
                self.assertEqual(result['school_name']['review_reason'], 'CONFLICT')

    def test_signature_context_does_not_cross_pages_or_change_diploma_ranking(self):
        self.assertEqual(fields('示例大学', '校长：测试乙')['school_name']['value'], '示例大学')
        conflict = fields('示例大学', '另一大学', '校长：测试乙')['school_name']
        self.assertEqual(conflict['review_reason'], 'CONFLICT')
        conflict = fields('示例大学\n另一大学\n校长：测试乙', kind='DIPLOMA')['school_name']
        self.assertEqual(conflict['review_reason'], 'CONFLICT')

    def test_award_date_accepts_peripheral_marks_missing_day_and_month_precision(self):
        for printed, expected in (('（二O二五年 六月 十九 日', '2025-06-19'),
                                  ('(2025年6月19日)', '2025-06-19'),
                                  ('2025年6月19）。', '2025-06-19'),
                                  ('二〇二五年 六 月 十九', '2025-06-19'),
                                  ('（2025年6月）', '2025-06')):
            with self.subTest(printed=printed):
                labelled = fields(f'授予日期：{printed}')['award_date']
                footer = fields(f'证书编号：00O123\n{printed}')['award_date']
                inline = fields(f'证书编号：00O123 {printed} 查询：说明')
                for item in (labelled, footer, inline['award_date']):
                    self.assertEqual(item['value'], expected)
                    self.assertIn(printed.rstrip('。'), item['source']['raw_text'])
                self.assertEqual(inline['certificate_no']['value'], '00O123')

    def test_spaced_full_number_labels_anchor_degree_date(self):
        for label in ('证 书 编 号', '学 位 证 书 编 号', '证书号码'):
            with self.subTest(label=label):
                result = fields(f'{label}：00O123\n（2025年6月19）')
                self.assertEqual(result['certificate_no']['value'], '00O123')
                self.assertEqual(result['award_date']['value'], '2025-06-19')

    def test_unrelated_number_labels_and_arbitrary_dates_are_not_anchors(self):
        for label in ('编号', '书编号', '档案证书编号', '身份证编号'):
            with self.subTest(label=label):
                result = fields(f'{label}：000123\n（2025年6月19日）')
                self.assertIsNone(result['certificate_no']['value'])
                self.assertIsNone(result['award_date']['value'])
        self.assertIsNone(fields('（2025年6月19日）')['award_date']['value'])

    def test_invalid_masked_or_unknown_date_suffix_is_not_guessed(self):
        for printed in ('2025年2月30', '2025年6月0', '2025年6月32',
                        '2025年6月1*', '2025年6月**', '2025年6月19 未知说明'):
            with self.subTest(printed=printed):
                self.assertIsNone(fields(f'证书编号：000123\n（{printed}）')['award_date']['value'])
                self.assertIsNone(fields(f'授予日期：{printed}')['award_date']['value'])

    def test_birth_and_study_dates_never_become_award(self):
        for text in ('出生日期：\n（2003年10月27日）\n证书编号：000123',
                     '出生日期：\n2003年10月27日\n证书编号：000123',
                     '于2021年9月至2025年6月在本校测试专业学习。\n证书编号：000123'):
            with self.subTest(text=text):
                self.assertIsNone(fields(text)['award_date']['value'])
        for key, label in (('birth_date', '出生日期'), ('enroll_date', '入学日期'), ('graduate_date', '毕业日期')):
            self.assertIsNone(fields(f'{label}：2025年6月19', kind='DIPLOMA')[key]['value'])

    def test_competing_award_dates_remain_conflicts(self):
        for text in ('证书编号：000123\n（2025年6月19）\n2025年6月20日',
                     '授予日期：2025年6月20日\n证书编号：000123\n（2025年6月19）'):
            with self.subTest(text=text):
                result = fields(text)['award_date']
                self.assertIsNone(result['value'])
                self.assertEqual(result['review_reason'], 'CONFLICT')

    def test_date_tolerance_does_not_reconstruct_number_digits(self):
        for token in ('000123****', '000123 456789', '000123 未知说明'):
            with self.subTest(token=token):
                self.assertIsNone(fields(f'证书编号：{token}')['certificate_no']['value'])


if __name__ == '__main__':
    unittest.main()
