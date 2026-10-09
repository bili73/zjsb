"""Business exclusions also govern review completion, not just view filters."""
import copy
import unittest
from sqlalchemy import text
import test_business_api as business_tests
from ocr_app.extraction import extract_result, _medical_item, issue
from ocr_app.review import apply_review, blockers
from ocr_app.task_store import public_result, TaskError


def medical_result():
    result = extract_result([], 'MEDICAL_REPORT')
    result['review_issues'] = []
    result['limitations'] = []
    result = apply_review(result, {'fields':{'name':'测试甲','gender':'男','exam_date':'2026-10-01'}}, actor='synthetic')
    result['items'] = [_medical_item(name, value, None, None, None, None, {'page':1}, [name,value])
                       for name,value in [('身高','180'),('体重','80'),(' 小 结： ','原始小结内容'),('体重指数','25')]]
    for item in result['items']:
        item.pop('abnormal_exclusion_reason',None)
        item['need_review'] = True
    # A historical spurious summary row even has an unresolvable conflict.
    result['items'][2]['review_issues'].append(issue('CONFLICT','历史小结冲突'))
    result['items'][3].update(review_issues=[],need_review=False)
    return result


class MedicalReviewScopeTests(unittest.TestCase):
    def test_excluded_problems_do_not_block_completion_or_change_original_evidence(self):
        original = medical_result()
        before = copy.deepcopy(original)
        current = apply_review(original, {}, actor='synthetic')
        self.assertEqual(current['status'],'COMPLETED')
        self.assertEqual(blockers(current),[])
        self.assertEqual(original,before)
        self.assertEqual(len(current['items']),4)
        for old,new in zip(before['items'][:3], current['items'][:3]):
            self.assertFalse(new['need_review'])
            self.assertEqual(new['review_issues'],old['review_issues'])
            self.assertEqual(new['source'],old['source'])
            self.assertEqual(new['result_raw'],old['result_raw'])
            self.assertNotIn('reviewed_by',new)
        self.assertEqual(current['items'][2]['abnormal_exclusion_reason'],'SECTION_SUMMARY')

    def test_bmi_and_longer_names_missingness_still_blocks_and_coverage_is_not_bypassed(self):
        for label in ['体重指数','BMI','身高体重血压','合成小结标志物']:
            result = medical_result()
            target = result['items'][3]
            target['name'] = label
            target['review_issues'] = [issue('MISSING','真实项目缺失')]
            reviewed = apply_review(result,{},actor='synthetic')
            self.assertEqual(reviewed['status'],'NEED_REVIEW')
            self.assertEqual([p['field'] for p in blockers(reviewed)],[target['item_id']])
        result = medical_result()
        result['review_issues'] = [issue('INCOMPLETE_OUTPUT','尚有未识别页面')]
        self.assertEqual(apply_review(result,{},actor='synthetic')['status'],'NEED_REVIEW')

    def test_legacy_read_projection_suppresses_only_review_noise_and_keeps_state(self):
        original = medical_result()
        original.update(status='NEED_REVIEW',state='NEED_REVIEW')
        before = copy.deepcopy(original)
        projected = public_result(original)
        self.assertEqual(original,before)
        self.assertEqual(projected['status'],'NEED_REVIEW')
        self.assertEqual([i['need_review'] for i in projected['items']],[False,False,False,False])
        self.assertEqual([i['review_issues'] for i in projected['items']],[i['review_issues'] for i in before['items']])

    def test_manual_rename_reenters_review_scope_and_rejects_derived_override(self):
        result = medical_result()
        identifier = result['items'][0]['item_id']
        changed = apply_review(result,{'items':[{'item_id':identifier,'name':'体重指数'}]},actor='synthetic')
        self.assertEqual(changed['status'],'NEED_REVIEW')
        self.assertEqual([p['field'] for p in blockers(changed)],[identifier])
        with self.assertRaises(TaskError):
            apply_review(result,{'items':[{'item_id':identifier,'abnormal_exclusion_reason':None}]},actor='synthetic')


class MedicalReviewScopeHTTPTests(unittest.TestCase):
    setUp = business_tests.BusinessAPITests.setUp
    upload = business_tests.BusinessAPITests.upload

    def test_legacy_save_completes_with_bmi_resolved_and_history_unchanged(self):
        created = self.upload('MEDICAL_REPORT').json()
        store = self.business.store
        task = store.claim_next()
        result = medical_result()
        result.update(status='NEED_REVIEW',state='NEED_REVIEW')
        store.publish(task,result)
        identifier = created['task_ids'][0]
        url = '/api/v1/tasks/'+identifier
        with self.business.engine.connect() as c:
            frozen = c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'),{'id':identifier}).scalar_one()
        read = self.client.get(url+'/result',headers=self.headers).json()
        self.assertTrue(all(not i['need_review'] for i in read['items']))
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'),{'id':identifier}).scalar_one(),frozen)
        saved = self.client.post(url+'/review',headers=self.headers,json={'run_id':read['run_id'],'expected_revision':read['result_revision']})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['status'],'COMPLETED')
        reloaded = self.client.get(url+'/result',headers=self.headers).json()
        self.assertEqual(reloaded['status'],'COMPLETED')
        self.assertEqual(reloaded['result_revision'],read['result_revision']+1)
        self.assertEqual(len(reloaded['items']),4)
        self.assertEqual(reloaded['items'][2]['result_raw'],'原始小结内容')


if __name__=='__main__':unittest.main()
