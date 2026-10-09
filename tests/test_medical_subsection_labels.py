"""Column-summary labels are evidence, not individual medical tests."""
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from ocr_app.extraction import extract_result


def block(text):
    return dict(text=text,page=1,region_id=str(uuid4()),bbox=[0,0,1,1],extraction_method='ocr')


def table(label):
    return ('<table><tr><th>项目</th><th>检测结果</th><th>风险等级</th><th>异常诊断</th></tr>'
            '<tr><td>合成检测</td><td>2↑</td><td>B</td><td>合成异常</td></tr>'
            f'<tr><td>{label}</td><td>小结内的实际异常内容</td><td>B</td><td>合成异常描述</td></tr>'
            '<tr><td>合成小结标志物</td><td>3</td><td>A</td><td></td></tr></table>')


class MedicalSubsectionLabelTests(unittest.TestCase):
    def test_exact_summary_labels_are_not_items_but_evidence_survives(self):
        for label in ['小结','小 结',' 小结： ','小结:']:
            with self.subTest(label=label):
                evidence=block(table(label))
                original=evidence.copy()
                result=extract_result([evidence],'MEDICAL_REPORT',complete=True)
                self.assertEqual([item['name'] for item in result['items']],['合成检测','合成小结标志物'])
                self.assertEqual([item['name'] for item in result['abnormal_summary']],['合成检测'])
                self.assertIn('小结内的实际异常内容',result['generic']['full_text'])
                self.assertEqual(result['generic']['blocks'][0]['text'],original['text'])
                self.assertEqual(evidence,original)
                self.assertEqual(result['items'][0]['abnormal_flag'],'HIGH')
                self.assertEqual(result['items'][0]['result_raw'],'2↑')
                self.assertEqual(result['stats']['total'],2)

    def test_summary_count_is_independent_of_column_summary(self):
        heading=block('您共有1项异常需进一步检查并治疗：\n1. 合成清单条目\n总检医师：')
        with_label=extract_result([block(table('小结')),heading],'MEDICAL_REPORT',complete=True)
        without=table('小结').replace('<tr><td>小结</td><td>小结内的实际异常内容</td><td>B</td><td>合成异常描述</td></tr>','')
        without_label=extract_result([block(without),heading],'MEDICAL_REPORT',complete=True)
        for result in [with_label,without_label]:
            self.assertEqual(result['report_summary']['declared_count'],1)
            self.assertEqual(len(result['report_summary']['findings']),1)
            self.assertEqual(result['report_summary']['count_check'],'match')
        self.assertEqual([i['name'] for i in with_label['items']],[i['name'] for i in without_label['items']])


if __name__=='__main__':unittest.main()
