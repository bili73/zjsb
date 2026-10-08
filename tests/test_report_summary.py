import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_report_summary


def block(text, page=3, y=.1):
    return dict(text=text, page=page, bbox=[.1, y, .9, y + .05],
                region_id=str(uuid4()), extraction_method='pdf_text')


def rows(numbers=(1, 2), method='pdf_text'):
    text = '<table><tr><td>序号</td><td>项目</td><td>异常诊断</td></tr>'
    text += ''.join(f'<tr><td>{n}</td><td>合成项目</td><td>报告原有文字</td></tr>' for n in numbers) + '</table>'
    value = block(text, y=.3)
    value['extraction_method'] = method
    value['table_rows'] = [dict(bbox=[.1, .3 + i * .1, .9, .4 + i * .1]) for i in range(len(numbers) + 1)]
    return value


class ReportSummaryTests(unittest.TestCase):
    def test_bare_overall_heading_is_not_a_reliable_list(self):
        summary = extract_report_summary([block('总检结论\n健康指导')])
        self.assertEqual(summary['scope'], 'unidentified')
        self.assertEqual(summary['findings'], [])

    def test_native_bounded_table_has_independent_coverage_and_row_source(self):
        table = rows()
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), table])
        self.assertEqual(summary['count_check'], 'match')
        self.assertEqual(summary['scope'], 'follow_up_required')
        self.assertEqual(summary['findings'][0]['sources'][0]['bbox'], table['table_rows'][1]['bbox'])
        self.assertEqual(summary['findings'][0]['sources'][0]['bbox_kind'], 'row')

    def test_ocr_table_cannot_claim_native_local_coverage(self):
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), rows(method='ocr')])
        self.assertEqual(summary['count_check'], 'unverified')

    def test_second_header_tier_is_not_a_missing_data_row(self):
        table = rows()
        table['text'] = table['text'].replace('</tr>', '</tr><tr><td></td><td></td><td></td><td>复查建议</td><td>复查项目</td><td>就诊科室</td><td>用药指导</td></tr>', 1)
        table['table_rows'].insert(1, dict(bbox=[.1, .35, .9, .4]))
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), table])
        self.assertEqual(summary['count_check'], 'match')
        self.assertEqual(len(summary['findings']), 2)

    def test_duplicate_numbers_and_extra_rows_are_not_matching(self):
        for numbers in [(1, 1), (1, 2, 3), (1, 3)]:
            summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), rows(numbers)])
            self.assertEqual(summary['count_check'], 'mismatch')

    def test_unrelated_lab_table_and_later_section_are_excluded(self):
        lab = block('<table><tr><td>序号</td><td>项目</td><td>结果</td></tr><tr><td>1</td><td>项目</td><td>5</td></tr></table>', y=.3)
        later = rows(); later['page'] = 4
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), lab, block('健康建议', y=.8), later])
        self.assertEqual(summary['findings'], [])
        self.assertEqual(summary['count_check'], 'unverified')

    def test_missing_geometry_keeps_table_reviewable(self):
        table = rows(); table.pop('table_rows')
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), table])
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['count_check'], 'unverified')

    def test_contents_mention_does_not_hide_actual_overall_list(self):
        summary = extract_report_summary([block('目录\n总检结论\n健康指导', page=2),
                                          block('总检结论\n\uf076 合成甲\n\uf076 合成乙\n异常结果解释', page=3)])
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['sources'][0]['page'], 3)
        self.assertIsNone(summary['declared_count'])

    def test_native_follow_up_table_continues_on_next_page_without_end_title(self):
        first = rows((1,)); first['page'] = 1
        second = rows((2,)); second['page'] = 2
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：', page=1), first, second], complete=True)
        self.assertEqual([f['reported_number'] for f in summary['findings']], ['1', '2'])
        self.assertEqual(summary['count_check'], 'match')

    def test_missing_continuation_without_boundary_is_not_false_mismatch(self):
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), rows((1,))], complete=True)
        self.assertEqual(summary['count_check'], 'unverified')

    def test_full_follow_up_title_in_contents_does_not_hide_body_table(self):
        summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：', page=1),
                                          block('您共有2项异常需进一步检查并治疗：'), rows()], complete=True)
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['sources'][0]['page'], 3)
        self.assertEqual(summary['count_check'], 'match')

    def test_nonadjacent_or_ocr_tables_are_not_assumed_native_continuations(self):
        for page, method in [(5, 'pdf_text'), (4, 'ocr')]:
            later = rows((2,), method=method); later['page'] = page
            summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), rows((1,)), later], complete=True)
            self.assertEqual(len(summary['findings']), 1)
            self.assertEqual(summary['count_check'], 'unverified')

    def test_ocr_title_outside_table_in_same_block_is_not_discarded(self):
        table = rows(method='ocr')
        table['text'] = '您共有2项异常需进一步检查并治疗：\n' + table['text']
        original = table['text']
        summary = extract_report_summary([table])
        self.assertEqual(summary['scope'], 'follow_up_required')
        self.assertEqual(summary['declared_count'], 2)
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['count_check'], 'unverified')
        self.assertEqual(table['text'], original)

    def test_duplicate_required_header_is_not_first_column_wins(self):
        for label in ('序号', '项目', '异常诊断'):
            table = rows()
            table['text'] = table['text'].replace(f'<td>{label}</td>', f'<td>{label}</td><td>{label}</td>', 1)
            summary = extract_report_summary([block('您共有2项异常需进一步检查并治疗：'), table])
            self.assertEqual(summary['findings'], [])
            self.assertEqual(summary['count_check'], 'unverified')


if __name__ == '__main__':
    unittest.main()
