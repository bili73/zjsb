"""Evidence-scoped HR medical fields and conservative diagnosis association."""
from pathlib import Path
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_result


def block(text, page=7, y=.1, rows=None):
    value = dict(text=text, page=page, region_id=str(uuid4()), extraction_method='pdf_text', bbox=[.1,y,.9,y+.05])
    if rows is not None:
        value['table_rows'] = rows
    return value


def table(rows):
    return '<table>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</table>'


PERSONAL = [['姓 名','测试甲','性 别','男'],['年 龄','30岁','体检日期','2026-10-01'],
            ['婚姻状况','未婚','手机号码','13800000000'],['工作单位','示例单位','','']]


class HRMedicalProfileTests(unittest.TestCase):
    def fields(self, evidence):
        return {f['key']: f for f in extract_result(evidence,'MEDICAL_REPORT')['fields']}

    def test_personal_table_moves_and_overrides_unscoped_dates(self):
        title=block('一、个人信息',7,.1)
        grid=block(table(PERSONAL),7,.2,rows=[{'bbox':[.1,.2,.9,.3],'cell_bboxes':[[.1,.2,.2,.3],[.2,.2,.5,.3],[.5,.2,.6,.3],[.6,.2,.9,.3]]}])
        fields=self.fields([block('一、个人信息 ........ 7',1),title,grid,
                            block('检查日期：2026-09-30',8),block('采样日期：2026-10-02',9)])
        expected=dict(name='测试甲',gender='M',age=30,exam_date='2026-10-01')
        for key,value in expected.items():
            self.assertEqual(fields[key]['value'],value,key)
            self.assertEqual(fields[key]['source']['page'],7)
        self.assertEqual(fields['name']['source']['bbox_kind'],'cell')

    def test_toc_or_next_section_table_does_not_supply_personal_data(self):
        for heading in ('二、其他信息','2. 其他信息','二 其他信息','二：其他信息'):
            with self.subTest(heading=heading):
                fields=self.fields([block('一、个人信息 ........ 7',1),block(table(PERSONAL),1,.2),
                                    block('一、个人信息',7),block(heading,7,.2),block(table(PERSONAL),7,.3)])
                for key in ('name','gender','age','exam_date'):
                    self.assertIsNone(fields[key]['value'],key)

    def test_untitled_legacy_labels_remain_compatible_but_toc_cannot_supply_values(self):
        self.assertEqual(self.fields([block('姓名：测试甲\n性别：男\n年龄：30')])['name']['value'],'测试甲')
        fields=self.fields([block('一、个人信息 ........ 7'),block(table(PERSONAL),7,.2)])
        self.assertTrue(all(fields[k]['value'] is None for k in ('name','gender','age','exam_date')))

    def test_duplicate_scoped_value_stays_conflicted_and_missing_does_not_fallback(self):
        rows=PERSONAL+[ ['姓名','测试乙','',''] ]
        fields=self.fields([block('一、个人信息'),block(table(rows),7,.2),block('姓名：测试甲',8)])
        self.assertIsNone(fields['name']['value'])
        self.assertEqual(fields['name']['review_reason'],'CONFLICT')
        blank=[r[:] for r in PERSONAL];blank[1][3]=''
        fields=self.fields([block('一、个人信息'),block(table(blank),7,.2),block('检查日期：2026-01-01',8)])
        self.assertIsNone(fields['exam_date']['value'])

    def test_grade_adds_abnormal_without_erasing_arrows_or_comparisons(self):
        rows=[['项目名称','检测结果','参考范围','风险等级'],['项目甲','2','1-3','B'],
              ['项目乙','4↑','1-3','/'],['项目丙','4','1-3','A'],['项目丁','文字','','']]
        items=extract_result([block(table(rows))],'MEDICAL_REPORT')['items']
        self.assertEqual((items[0]['abnormal_flag'],items[0]['abnormal_basis']),('ABNORMAL','report_grade'))
        self.assertEqual(items[0]['risk_grade'],'B')
        self.assertEqual(items[1]['abnormal_flag'],'HIGH')
        self.assertEqual(items[2]['abnormal_flag'],'HIGH')
        self.assertEqual(items[3]['abnormal_flag'],'UNKNOWN')
        self.assertTrue(any(i['code']=='MISSING' for i in items[3]['review_issues']))

    def test_same_row_diagnosis_has_its_own_source(self):
        items=extract_result([block(table([['项目名称','检测结果','等级','异常诊断'],
            ['项目甲','偏离','B','报告诊断甲']]))],'MEDICAL_REPORT')['items']
        self.assertEqual(items[0]['diagnosis'],'报告诊断甲')
        self.assertEqual(len(items[0]['diagnosis_sources']),1)

    def summary_evidence(self, detail_rows):
        return [block('您共有 1项异常需进一步检查并治疗：',2,.1),
            block(table([['序号','项目','异常诊断','风险等级'],['1','项目甲','报告诊断甲','/']]),2,.2,
                  rows=[{},dict(bbox=[.1,.3,.9,.4])]),block('健康建议',2,.8),
            block(table([['项目名称','检测结果','风险等级']]+detail_rows),3,.2)]

    def test_unique_summary_link_binds_result_and_diagnosis_without_grade_overwrite(self):
        result=extract_result(self.summary_evidence([['项目甲','4↑','B']]),'MEDICAL_REPORT')
        item=result['items'][0];finding=result['report_summary']['findings'][0]
        self.assertEqual(item['diagnosis'],'报告诊断甲')
        self.assertEqual(item['risk_grade'],'B')
        self.assertEqual(item['diagnosis_sources'][0]['page'],2)
        self.assertEqual(finding['diagnosis'],'报告诊断甲')
        self.assertEqual(finding['risk_grade'],'/')
        self.assertEqual(finding['result_raw'],'4↑')
        self.assertEqual(finding['result_sources'][0]['page'],3)
        self.assertEqual(result['report_summary']['count_check'],'match')

    def test_duplicate_detail_names_do_not_guess_diagnosis_or_result(self):
        result=extract_result(self.summary_evidence([['项目甲','4','B'],['项目甲','5','C']]),'MEDICAL_REPORT')
        finding=result['report_summary']['findings'][0]
        self.assertIsNone(finding['result_raw'])
        self.assertTrue(any(i['code']=='CONFLICT' for i in finding['review_issues']))
        self.assertTrue(all(i['diagnosis'] is None for i in result['items']))

    def test_duplicate_same_value_detail_still_does_not_link(self):
        result=extract_result(self.summary_evidence([['项目甲','4','B'],['项目甲','4','B']]),'MEDICAL_REPORT')
        finding=result['report_summary']['findings'][0]
        self.assertIsNone(finding['result_raw'])
        self.assertTrue(any(i['code']=='CONFLICT' for i in finding['review_issues']))

    def test_multiple_summary_diagnoses_keep_all_sources_without_selecting_one(self):
        evidence=self.summary_evidence([['项目甲','4','B']])
        evidence[0]['text']='您共有 2项异常需进一步检查并治疗：'
        evidence[1]=block(table([['序号','项目','异常诊断','风险等级'],
            ['1','项目甲','报告诊断甲','B'],['2','项目甲','报告诊断乙','C']]),2,.2,
            rows=[{},dict(bbox=[.1,.3,.9,.4]),dict(bbox=[.1,.4,.9,.5])])
        result=extract_result(evidence,'MEDICAL_REPORT')
        item=result['items'][0]
        self.assertIsNone(item['diagnosis'])
        self.assertEqual(len(item['diagnosis_sources']),2)
        self.assertTrue(any(i['code']=='CONFLICT' for i in item['review_issues']))
        self.assertEqual(result['report_summary']['count_check'],'match')
        self.assertIsNone(result['stats']['total'])

    def test_missing_detection_result_keeps_reliably_graded_row_for_review(self):
        result=extract_result([block(table([['项目名称','检测结果','风险等级','异常诊断'],
            ['项目甲','','B','报告诊断甲']]))],'MEDICAL_REPORT')
        self.assertEqual(len(result['items']),1)
        item=result['items'][0]
        self.assertEqual(item['result_raw'],'')
        self.assertIsNone(item['value_num'])
        self.assertEqual(item['abnormal_flag'],'ABNORMAL')
        self.assertEqual(item['risk_grade'],'B')
        self.assertTrue(any(i['code']=='MISSING' for i in item['review_issues']))

    def test_detail_units_and_source_rows_are_not_cross_assigned(self):
        evidence=self.summary_evidence([['项目甲','4','B']])
        evidence[-1]=block(table([['项目名称','检测结果','单位','风险等级'],
            ['项目甲','4','mg/L','B'],['项目甲','0.4','g/L','B']]),3,.2)
        result=extract_result(evidence,'MEDICAL_REPORT')
        self.assertEqual([i['unit'] for i in result['items']],['mg/L','g/L'])
        self.assertIsNone(result['report_summary']['findings'][0]['result_raw'])

    def test_summary_grade_is_independent_when_diagnoses_conflict(self):
        evidence=self.summary_evidence([['项目甲','2','A']])
        evidence[1]=block(table([['序号','项目','异常诊断','风险等级'],
            ['1','项目甲','报告诊断甲','B']]),2,.2,rows=[{},dict(bbox=[.1,.3,.9,.4])])
        evidence[-1]=block(table([['项目名称','检测结果','参考范围','风险等级','异常诊断'],
            ['项目甲','2','1-3','A','正常']]),3,.2)
        result=extract_result(evidence,'MEDICAL_REPORT')
        item=result['items'][0];finding=result['report_summary']['findings'][0]
        self.assertEqual((item['abnormal_flag'],item['abnormal_basis']),('ABNORMAL','report_grade'))
        self.assertEqual(item['risk_grade'],'A')
        self.assertEqual(finding['risk_grade'],'B')
        self.assertIsNone(item['diagnosis'])
        self.assertEqual({s['page'] for s in item['diagnosis_sources']},{2,3})
        self.assertTrue(any(i['code']=='CONFLICT' and '等级' in i['message'] for i in item['review_issues']))
        self.assertEqual(len(result['abnormal_summary']),1)
        evidence[-1]['text']=table([['项目名称','检测结果','参考范围','风险等级','异常诊断'],
            ['项目甲','4↑','1-3','A','另一诊断']])
        high=extract_result(evidence,'MEDICAL_REPORT')['items'][0]
        self.assertEqual((high['abnormal_flag'],high['abnormal_basis']),('HIGH','report_marker'))

    def test_diploma_retired_labels_still_bound_neighbor_values(self):
        result=extract_result([block('毕业证书\n学校名称：示例大学 学习形式：普通全日制\n专业：软件工程 校长：签字甲\n证书编号：123456 校长：签字甲')],'DIPLOMA')
        fields={f['key']:f for f in result['fields']}
        self.assertNotIn('study_mode',fields)
        self.assertNotIn('principal',fields)
        self.assertEqual(fields['school_name']['value'],'示例大学')
        self.assertEqual(fields['major']['value'],'软件工程')
        self.assertEqual(fields['certificate_no']['value'],'123456')
        degree=extract_result([block('学士学位证书\n学习形式：普通全日制')],'DEGREE_CERT')
        self.assertEqual(next(f for f in degree['fields'] if f['key']=='study_mode')['value'],'普通全日制')


if __name__ == '__main__':
    unittest.main()
