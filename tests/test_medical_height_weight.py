"""Height and weight remain evidence but are outside the anomaly scope."""
import copy
import io
import unittest
from sqlalchemy import text
from test_hr_medical_profile import block, table
import test_business_api as business_tests
from ocr_app.extraction import extract_result
from ocr_app.review import apply_review
from ocr_app.task_store import public_result


def evidence():
    return [block('姓名：测试甲 性别：男 检查日期：2026-10-01'),
            block(table([['项目','检测结果','风险等级','异常诊断'],
                         ['身高','180↑','B','测量记录'], ['体重','90↑','B','测量记录'],
                         ['体重指数','30↑','B','偏重'], ['BMI','30↑','B','偏重'],
                         ['身高体重血压','140↑','B','需核对'], ['体重变化','2↑','B','需核对']])),
            block('您共有1项异常需进一步检查并治疗：\n1. 体重指数偏高\n总检医师：')]


class HeightWeightTests(unittest.TestCase):
    def test_exclusion_keeps_raw_facts_bmi_longer_names_and_summary(self):
        result = extract_result(evidence(), 'MEDICAL_REPORT', complete=True)
        self.assertEqual(len(result['items']), 6)
        self.assertEqual([i['name'] for i in result['abnormal_summary']], ['体重指数','BMI','身高体重血压','体重变化'])
        for item in result['items'][:2]:
            self.assertEqual(item.get('abnormal_exclusion_reason'), 'HEIGHT_WEIGHT')
            self.assertEqual(item['abnormal_flag'], 'HIGH')
            self.assertEqual(item['risk_grade'], 'B')
            self.assertIn('↑', item['result_raw'])
        self.assertEqual(result['stats']['total'], 4)
        self.assertEqual(result['stats']['abnormal'], 4)
        self.assertEqual(result['stats']['unknown'], 0)
        self.assertEqual(result['report_summary']['declared_count'], 1)
        self.assertEqual(result['report_summary']['count_check'], 'match')
        self.assertIn('180↑', result['generic']['full_text'])
        for label in [' 身 高： ', '体 重', '身高体重', '身高/体重', '身高、体重']:
            r = extract_result([block(table([['项目','检测结果','风险等级'],[label,'5↑','B']]))], 'MEDICAL_REPORT', complete=True)
            self.assertEqual(len(r['items']), 1)
            self.assertEqual(r['abnormal_summary'], [])
            self.assertEqual(r['stats']['total'], 0)

    def test_legacy_projection_does_not_rewrite_and_preserves_null_stats(self):
        old = extract_result(evidence(), 'MEDICAL_REPORT', complete=True)
        for item in old['items']:
            item.pop('abnormal_exclusion_reason', None)
        old['abnormal_summary'] = copy.deepcopy(old['items'])
        old['stats'] = dict(total=6, normal=0, abnormal=6, unknown=0, categories=[])
        before = copy.deepcopy(old)
        current = public_result(old)
        self.assertEqual(old, before)
        self.assertEqual(len(current['abnormal_summary']), 4)
        self.assertEqual(current['stats']['total'], 4)
        old['stats'] = dict(total=None, normal=None, abnormal=None, unknown=None, categories=[])
        self.assertIsNone(public_result(old)['stats']['total'])

    def test_manual_renaming_recomputes_exclusion_without_client_override(self):
        old = extract_result(evidence(), 'MEDICAL_REPORT', complete=True)
        body = {'items':[{'item_id':old['items'][0]['item_id'],'name':'体重指数'},
                         {'item_id':old['items'][2]['item_id'],'name':'身高'}]}
        current = apply_review(old, body, actor='synthetic-reviewer')
        self.assertIsNone(current['items'][0].get('abnormal_exclusion_reason'))
        self.assertEqual(current['items'][2].get('abnormal_exclusion_reason'), 'HEIGHT_WEIGHT')
        self.assertEqual(current['stats']['total'], 4)
        self.assertEqual(current['stats']['abnormal'], 4)


class HeightWeightHTTPTests(unittest.TestCase):
    setUp = business_tests.BusinessAPITests.setUp
    upload = business_tests.BusinessAPITests.upload

    def test_save_reload_filters_keep_statistics_and_excel_explains_exclusion(self):
        created = self.upload('MEDICAL_REPORT').json()
        store = self.business.store
        worker = store.claim_next()
        old = extract_result(evidence(), 'MEDICAL_REPORT', complete=True)
        for item in old['items']:
            item.pop('abnormal_exclusion_reason', None)
        old['abnormal_summary'] = copy.deepcopy(old['items'])
        old['stats'] = dict(total=6, normal=0, abnormal=6, unknown=0, categories=[])
        store.publish(worker, old)
        identifier = created['task_ids'][0]
        url = '/api/v1/tasks/' + identifier
        with self.business.engine.connect() as c:
            frozen = c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'), {'id':identifier}).scalar_one()
        all_items = self.client.get(url+'/result?items_filter=all', headers=self.headers).json()
        abnormal = self.client.get(url+'/result?items_filter=abnormal', headers=self.headers).json()
        unknown = self.client.get(url+'/result?items_filter=unknown', headers=self.headers).json()
        self.assertEqual(len(all_items['items']), 6)
        self.assertEqual(len(abnormal['items']), 4)
        self.assertEqual(unknown['items'], [])
        self.assertEqual(all_items['stats'], abnormal['stats'])
        self.assertEqual(all_items['stats'], unknown['stats'])
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'), {'id':identifier}).scalar_one(), frozen)
        body = dict(run_id=all_items['run_id'], expected_revision=all_items['result_revision'], fields={'exam_projects':'内科检查；眼科常规'})
        saved = self.client.post(url+'/review', headers=self.headers, json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        reloaded = self.client.get(url+'/result', headers=self.headers).json()
        self.assertFalse({'report_no','package_name','phone','work_unit','marital_status'} & set(reloaded['basic_info']))
        self.assertTrue({'report_date','institution'} <= set(reloaded['basic_info']))
        self.assertEqual(reloaded['basic_info']['exam_projects']['value'], '内科检查；眼科常规')
        self.assertEqual(len(reloaded['abnormal_summary']), 4)
        response = self.client.post('/api/v1/export', headers=self.headers, json={'task_ids':[identifier]})
        self.assertEqual(response.status_code, 200)
        from openpyxl import load_workbook
        sheet = load_workbook(io.BytesIO(response.content))['审核记录台账']
        rows = list(sheet.values)
        keys = rows[0]
        records = [dict(zip(keys, row)) for row in rows[1:]]
        # The independent prose finding cannot be uniquely linked; keep it explicit.
        self.assertEqual(len(records), 1)
        abnormal = records[0]['异常指标']
        self.assertIn('未关联检测结果', abnormal)
        self.assertNotRegex(abnormal,r'(?:^|、)(?:身高|体重|小结) ')
        self.assertIn('身高体重血压 140',abnormal)
        self.assertIn('体重指数', abnormal)


if __name__ == '__main__':
    unittest.main()
