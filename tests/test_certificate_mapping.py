import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_fields


def fields(text, kind='DIPLOMA'):
    blocks = text if isinstance(text, list) else [text]
    return {f['key']: f for f in extract_fields(
        [dict(page=i + 1, text=t, extraction_method='ocr') for i, t in enumerate(blocks)], kind)}


class CertificateMappingTests(unittest.TestCase):
    def test_bare_identity_and_birth_precision(self):
        result = fields('测试甲，女，1990年1月生。', 'DEGREE_CERT')
        self.assertEqual([result[k]['value'] for k in ('name', 'gender', 'birth_date')],
                         ['测试甲', 'F', '1990-01'])
        self.assertIsNone(result['name']['confidence'])
        self.assertTrue(result['name']['need_review'])

    def test_major_before_label_and_multiline_level(self):
        result = fields('在本校测试工程\n专业 二年制专科\n学习，修完课程。')
        self.assertEqual(result['major']['value'], '测试工程')
        self.assertEqual(result['duration']['value'], '二年')
        self.assertEqual(result['education_level']['value'], '专科')

    def test_narrative_school_is_not_part_of_major(self):
        result = fields('在示例大学测试工程专业完成学习。')
        self.assertEqual(result['school_name']['value'], '示例大学')
        self.assertEqual(result['major']['value'], '测试工程')

    def test_school_alias_and_number_tail(self):
        result = fields('校（院）名：示例大学\n证书编号：000123 2020年6月1日 查询：说明')
        self.assertEqual(result['school_name']['value'], '示例大学')
        self.assertEqual(result['certificate_no']['value'], '000123')

    def test_spaced_print_labels_and_composite_school_name(self):
        result = fields('普通高等学校\n校 名：示例大学示例学院\n在示例大学示例学院测试工程专业 三 年制本 科学习。')
        self.assertEqual(result['school_name']['value'], '示例大学示例学院')
        self.assertEqual(result['major']['value'], '测试工程')
        self.assertEqual(result['duration']['value'], '三年')
        self.assertEqual(result['education_level']['value'], '本科')

    def test_isolated_footer_before_number(self):
        result = fields('校长：测试乙\n2020年6月\n证书编号：000123')
        self.assertEqual(result['issue_date']['value'], '2020-06')

    def test_study_interval_is_enrollment_and_graduation_with_separate_issue(self):
        result = fields('学生 测试甲，男，1990年1月1日生。\n于2017年9月至2020年6月在本校测试工程专业学习。\n发证日期：2020年7月')
        self.assertEqual(result['birth_date']['value'], '1990-01-01')
        self.assertEqual(result['enroll_date']['value'], '2017-09')
        self.assertEqual(result['issue_date']['value'], '2020-07')
        self.assertEqual(result['graduate_date']['value'], '2020-06')

    def test_footer_is_issue_or_award_not_birth(self):
        text = '证书编号：000123\n二〇二〇年六月十七日'
        self.assertEqual(fields(text)['issue_date']['value'], '2020-06-17')
        degree = fields(text, 'DEGREE_CERT')
        self.assertEqual(degree['award_date']['value'], '2020-06-17')
        self.assertIsNone(degree['birth_date']['value'])

    def test_multiline_degree_keeps_level_and_name_separate(self):
        result = fields('授予\n工学\n学士学位。', 'DEGREE_CERT')
        self.assertEqual(result['degree_category']['value'], '学士')
        self.assertEqual(result['degree_name']['value'], '工学学士')

    def test_candidates_from_every_source_and_degree_conflict(self):
        result = fields(['示例甲大学\n在本校测试甲专业学习。', '示例乙大学\n在本校测试乙专业学习。'])
        for key in ('school_name', 'major'):
            self.assertIsNone(result[key]['value'])
            self.assertEqual(result[key]['review_reason'], 'CONFLICT')
        result = fields('学士学位证书\n授予工学硕士学位。', 'DEGREE_CERT')
        self.assertIsNone(result['degree_category']['value'])
        self.assertEqual(result['degree_category']['review_reason'], 'CONFLICT')
        self.assertIsNone(result['degree_name']['value'])
        self.assertEqual(result['degree_name']['review_reason'], 'CONFLICT')

    def test_wrapped_birth_date_is_not_a_footer_date(self):
        result = fields('出生日期：\n1990年1月\n证书编号：000123')
        self.assertEqual(result['birth_date']['value'], '1990-01')
        self.assertIsNone(result['issue_date']['value'])

    def test_numbers_are_not_corrected_or_joined_and_ambiguous_dates_conflict(self):
        result = fields('证书编号：00O123 2020年6月1日\n2020年6月\n2020年7月')
        self.assertEqual(result['certificate_no']['value'], '00O123')
        self.assertIsNone(result['issue_date']['value'])
        self.assertEqual(result['issue_date']['review_reason'], 'CONFLICT')

    def test_unknown_number_remainder_is_not_silently_truncated(self):
        for tail in (' 456789', ' ****', '\t456789', ',456789', ' 未知说明'):
            with self.subTest(tail=tail):
                result = fields('证书编号：000123' + tail)
                self.assertIsNone(result['certificate_no']['value'])
                self.assertTrue(result['certificate_no']['need_review'])
        for tail in (' 2020年6月1日 查询：说明', ' 查询：说明', '\t校名：示例大学'):
            with self.subTest(tail=tail):
                self.assertEqual(fields('证书编号：000123' + tail)['certificate_no']['value'], '000123')

    def test_explicit_degree_level_and_full_name_mismatch_is_conflict(self):
        result = fields(['学位级别：学士', '学位名称：工学硕士'], 'DEGREE_CERT')
        for key in ('degree_category', 'degree_name'):
            self.assertIsNone(result[key]['value'])
            self.assertEqual(result[key]['review_reason'], 'CONFLICT')
        consistent = fields('学位级别：学士\n学位名称：工学学士', 'DEGREE_CERT')
        self.assertEqual(consistent['degree_category']['value'], '学士')
        self.assertEqual(consistent['degree_name']['value'], '工学学士')

    def test_same_value_across_pages_is_not_conflicting(self):
        result = fields(['姓名：测试甲\n校名：示例大学', '姓名：测试甲\n校名：示例大学'])
        self.assertEqual(result['name']['value'], '测试甲')
        self.assertEqual(result['school_name']['value'], '示例大学')

    def test_invalid_dates_and_non_identity_text_are_not_guessed(self):
        result = fields('出生日期：2020年2月30日\n校长：测试乙\n专业介绍：本校提供专业学习服务。\n2020年6月')
        self.assertIsNone(result['birth_date']['value'])
        self.assertIsNone(result['name']['value'])
        self.assertIsNone(result['major']['value'])
        self.assertIsNone(result['issue_date']['value'])

    def test_html_keeps_cell_boundaries(self):
        result = fields('<table><tr><td>姓名</td><td>测试甲</td><td>性别</td><td>女</td></tr><tr><td>校名</td><td>示例大学</td></tr></table>')
        self.assertEqual(result['name']['value'], '测试甲')
        self.assertEqual(result['gender']['value'], 'F')
        self.assertEqual(result['school_name']['value'], '示例大学')

    def test_medical_label_behavior_unchanged(self):
        result = fields('姓名：测试甲\n性别：女\n年龄：23岁\n体检机构：示例机构', 'MEDICAL_REPORT')
        self.assertEqual(result['name']['value'], '测试甲')
        self.assertEqual(result['gender']['value'], 'F')
        self.assertEqual(result['age']['value'], 23)


if __name__ == '__main__':
    unittest.main()
