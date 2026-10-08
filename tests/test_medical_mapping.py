import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_result


def evidence(text, page=1, y=.1):
    return dict(text=text, page=page, region_id=str(uuid4()), extraction_method='pdf_text', bbox=[.1, y, .9, y + .05])


def table(value, marker='', reference='1-3'):
    return evidence('<table><tr><td>项目</td><td>结果</td><td>提示</td><td>参考范围</td></tr>'
                    f'<tr><td>合成项目</td><td>{value}</td><td>{marker}</td><td>{reference}</td></tr></table>')


class MedicalMappingTests(unittest.TestCase):
    def test_explicit_latex_arrow_keeps_original(self):
        raw = r'4.00\uparrow'
        item = extract_result([table(raw)], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['result_raw'], raw)
        self.assertEqual(item['value_num'], 4.0)
        self.assertEqual(item['abnormal_flag'], 'HIGH')
        self.assertEqual(item['reported_abnormal_marker'], r'\uparrow')

    def test_unknown_marker_does_not_hide_result_arrow(self):
        item = extract_result([table('4.00↑', '*')], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['abnormal_flag'], 'HIGH')

    def test_negated_positive_is_not_positive(self):
        item = extract_result([table('未见阳性', reference='')], 'MEDICAL_REPORT')['items'][0]
        self.assertNotEqual(item['abnormal_flag'], 'POSITIVE')

    def test_result_unit_letter_is_not_an_abnormal_marker(self):
        item = extract_result([table('4.00 mg/L', reference='')], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['abnormal_flag'], 'UNKNOWN')
        self.assertIsNone(item['value_num'])

    def test_explicit_abnormal_positive_and_unqualified_positive_differ(self):
        result = extract_result([table('阳性', '异常', ''), table('阳性', '', '')], 'MEDICAL_REPORT')
        self.assertEqual(result['items'][0]['abnormal_basis'], 'report_marker')
        self.assertEqual(result['items'][1]['abnormal_basis'], 'unknown')
        self.assertEqual(len(result['abnormal_summary']), 1)

    def test_marker_range_conflict_remains_reviewable(self):
        item = extract_result([table('2.0↑')], 'MEDICAL_REPORT')['items'][0]
        self.assertIn('CONFLICT', [i['code'] for i in item['review_issues']])
        self.assertFalse(next(i for i in item['review_issues'] if i['code'] == 'CONFLICT')['can_accept'])

    def test_conflicting_marker_sources_are_not_silently_chosen(self):
        item = extract_result([table('4.0↑', '↓')], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['abnormal_flag'], 'UNKNOWN')
        self.assertIn('CONFLICT', [i['code'] for i in item['review_issues']])

    def test_direction_word_conflicts_with_result_arrow(self):
        item = extract_result([table('4.0↑', '偏低')], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['abnormal_flag'], 'UNKNOWN')
        self.assertIn('CONFLICT', [i['code'] for i in item['review_issues']])

    def test_duplicate_result_columns_do_not_choose_last_value(self):
        block = evidence('<table><tr><td>项目</td><td>结果</td><td>结果</td><td>参考范围</td></tr>'
                         '<tr><td>合成项目</td><td>20</td><td>5</td><td>0-10</td></tr></table>')
        result = extract_result([block], 'MEDICAL_REPORT')
        self.assertEqual(result['items'], [])
        self.assertTrue(any('重复' in text for text in result['limitations']))

    def test_invalid_latex_token_does_not_repair_digits(self):
        item = extract_result([table(r'4.001\uparrowExtra')], 'MEDICAL_REPORT')['items'][0]
        self.assertIsNone(item['value_num'])
        self.assertEqual(item['abnormal_basis'], 'unknown')

    def test_row_source_is_used_when_supplied(self):
        block = table('4.0↑')
        block['table_rows'] = [{'bbox': [.1,.1,.9,.2]}, {'bbox': [.1,.2,.9,.3]}]
        item = extract_result([block], 'MEDICAL_REPORT')['items'][0]
        self.assertEqual(item['source']['bbox'], [.1,.2,.9,.3])
        self.assertEqual(item['source']['bbox_kind'], 'row')


class MedicalConclusionTests(unittest.TestCase):
    def summary(self, blocks, complete=False):
        return extract_result(blocks, 'MEDICAL_REPORT', complete=complete)['report_summary']

    def test_user_title_is_located_without_fixed_page(self):
        summary = self.summary([evidence('您共有 2 项异常需进一步检查并治疗：\n1、合成发现甲\n2、合成发现乙\n总检医师：合成签名', 9)], True)
        self.assertEqual(summary['scope'], 'follow_up_required')
        self.assertEqual(summary['declared_count'], 2)
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['count_check'], 'match')
        self.assertEqual(summary['sources'][0]['page'], 9)

    def test_title_can_wrap_between_native_blocks(self):
        summary = self.summary([evidence('您共有', 7), evidence('2项异常需进一步检查并治疗：', 7, .2),
                                evidence('1、合成甲\n2、合成乙\n总检医师：合成签名', 7, .3)], True)
        self.assertEqual(summary['declared_count'], 2)
        self.assertEqual(len(summary['findings']), 2)

    def test_overall_findings_are_not_mixed_with_follow_up_scope(self):
        blocks = [evidence('总检结论\n• 总结甲\n• 总结乙\n名词解释', 4),
                  evidence('您共有 1项异常需进一步检查并治疗：\n1、进一步检查甲\n健康建议', 6)]
        summary = self.summary(blocks, True)
        self.assertEqual(summary['scope'], 'follow_up_required')
        self.assertEqual(summary['declared_count'], 1)
        self.assertEqual(len(summary['findings']), 1)
        self.assertNotIn('总结甲', summary['findings'][0]['text'])

    def test_observed_count_never_fills_missing_declaration(self):
        summary = self.summary([evidence('总检结论\n\uf076 合成发现甲\n\uf076 合成发现乙\n名词解释', 3)], True)
        self.assertEqual(summary['scope'], 'overall_conclusion')
        self.assertIsNone(summary['declared_count'])
        self.assertEqual(summary['count_check'], 'unverified')
        self.assertEqual(len(summary['findings']), 2)

    def test_count_match_requires_coverage_evidence(self):
        summary = self.summary([evidence('您共有 1项异常需进一步检查并治疗：\n1、合成甲')])
        self.assertEqual(summary['count_check'], 'unverified')

    def test_missing_list_and_unrelated_numbers_do_not_mean_zero(self):
        summary = self.summary([evidence('检查说明：发现3个合成结构。\n健康建议\n1、合成建议')], True)
        self.assertIsNone(summary['declared_count'])
        self.assertEqual(summary['findings'], [])
        self.assertEqual(summary['scope'], 'unidentified')

    def test_conflicting_declarations_are_not_arbitrarily_selected(self):
        blocks = [evidence('您共有2项异常需进一步检查并治疗：\n1、合成甲\n健康建议', 2),
                  evidence('您共有3项异常需进一步检查并治疗：\n1、合成乙\n健康建议', 5)]
        summary = self.summary(blocks, True)
        self.assertIsNone(summary['declared_count'])
        self.assertEqual(summary['count_check'], 'unverified')

    def test_extra_or_duplicate_numbered_findings_produce_mismatch(self):
        summary = self.summary([evidence('您共有2项异常需进一步检查并治疗：\n1、合成甲\n1、合成乙\n健康建议')], True)
        self.assertEqual(summary['count_check'], 'mismatch')

    def test_mismatched_summary_remains_reviewable(self):
        result = extract_result([evidence('您共有2项异常需进一步检查并治疗：\n1、合成甲\n健康建议')],
                                'MEDICAL_REPORT', complete=True)
        self.assertEqual(result['report_summary']['count_check'], 'mismatch')
        self.assertIn('CONFLICT', [i['code'] for i in result['review_issues']])

    def test_explicit_zero_needs_bounded_complete_section(self):
        summary = self.summary([evidence('您共有0项异常需进一步检查并治疗：\n健康建议')], True)
        self.assertEqual(summary['declared_count'], 0)
        self.assertEqual(summary['count_check'], 'match')


if __name__ == '__main__':
    unittest.main()
