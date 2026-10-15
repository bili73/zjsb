"""Explicit disputes use synthetic evidence; no production writes or inference."""
import copy
import unittest
from uuid import uuid4

import test_business_api as business_tests
from ocr_app.extraction import extract_result, issue
from ocr_app.export_disputes import export_disputes, number_length_warning
from ocr_app.exporting import required_export_blockers
from ocr_app.review import apply_review
from ocr_app.task_store import TaskError, public_result


def saved(kind='DIPLOMA', **values):
    result = extract_result([], kind)
    result.update(run_id=str(uuid4()), status='NEED_REVIEW')
    defaults = dict(name='测试姓名', school='测试大学', school_name='测试大学', major='测试专业',
                    certificate_no='123456789012345678', graduate_date='2020-06-30', gender='M',
                    age=20, mobile_number='13800138000', id_number='11010519491231002X',
                    card_number='6217851234567890123', bank_name='中国银行', education_level='本科')
    defaults.update(values)
    for field in result['fields']:
        field.update(value=defaults.get(field['key']), review_issues=[], candidates=[])
    return result


def ambiguous_medical_result():
    from test_interview_form import block
    rows = block('<table><tr><td>项目</td><td>结果</td><td>单位</td><td>参考范围</td></tr>'
                 '<tr><td>血糖</td><td>5.5</td><td>mmol/L</td><td>3.9-6.1</td></tr>'
                 '<tr><td>血糖</td><td>8.2</td><td>mmol/L</td><td>3.9-6.1</td></tr></table>')
    heading = block('您共有1项异常需进一步检查并治疗：')
    heading['bbox'] = [.1, .6, .9, .65]
    finding = block('<table><tr><td>序号</td><td>项目</td><td>异常诊断</td><td>等级</td></tr>'
                    '<tr><td>1</td><td>血糖</td><td>血糖增高</td><td>B</td></tr></table>')
    finding['bbox'] = [.1, .7, .9, .9]
    result = extract_result([rows, heading, finding], 'MEDICAL_REPORT', complete=True)
    for field in result['fields']:
        if field['key'] in {'name', 'gender', 'exam_date'}:
            field['value'] = {'name': '测试甲', 'gender': 'F', 'exam_date': '2026-10-01'}[field['key']]
    return result


class DisputeTests(unittest.TestCase):
    def test_legacy_acknowledgment_cannot_hide_unselected_medical_result(self):
        original = ambiguous_medical_result()
        disputes = export_disputes(original)
        self.assertTrue(disputes)
        original['_export_confirmations'] = [dict(dispute_id=d['dispute_id'], actor='old', confirmed_at='old')
                                             for d in disputes]
        self.assertTrue(export_disputes(original))
        reviewed = apply_review(original, {'confirm_export_disputes': True}, actor='operator')
        self.assertTrue(export_disputes(reviewed))
        self.assertEqual(reviewed['_export_confirmations'], [])

    def test_medical_item_needs_result_and_selected_diagnosis(self):
        for value, diagnosis_sources in [('', []), ('8.2', [{'raw_text': '两个诊断'}])]:
            with self.subTest(value=value):
                original = saved('MEDICAL_REPORT')
                original['items'] = [dict(item_id=str(uuid4()), name='血糖', result_raw=value, diagnosis=None,
                    diagnosis_sources=diagnosis_sources, review_issues=[issue('CONFLICT', '未选定')])]
                self.assertFalse(export_disputes(original)[0]['can_confirm'])
                reviewed = apply_review(original, {'confirm_export_disputes': True}, actor='operator')
                self.assertTrue(export_disputes(reviewed))

    def test_finding_metadata_edit_cannot_clear_unselected_association(self):
        original = ambiguous_medical_result()
        finding = original['report_summary']['findings'][0]
        for patch in [{'text': finding['text']}, {'risk_grade': 'C'}, {'result_item_id': None}]:
            with self.subTest(patch=patch):
                reviewed = apply_review(original, {'findings': [dict(finding_id=finding['finding_id'], **patch)],
                                                  'confirm_export_disputes': True}, actor='operator')
                self.assertTrue(export_disputes(reviewed))
                self.assertTrue(required_export_blockers(reviewed))
        explicit_absence = apply_review(original, {'findings': [dict(finding_id=finding['finding_id'],
            result_item_id=None, absence_reasons={'result_raw': 'NOT_ON_DOCUMENT'})],
            'confirm_export_disputes': True}, actor='operator')
        self.assertFalse(export_disputes(explicit_absence))

    def test_item_metadata_edit_keeps_unselected_diagnosis_conflict(self):
        original = ambiguous_medical_result()
        item = original['items'][0]
        item.update(diagnosis=None, diagnosis_sources=[{'raw_text': '两个诊断'}],
                    review_issues=[issue('CONFLICT', '多个诊断未选择')])
        reviewed = apply_review(original, {'items': [{'item_id': item['item_id'], 'unit': 'mmol/L'}],
                                          'confirm_export_disputes': True}, actor='operator')
        self.assertTrue(any(d['field'] == 'items[0]' for d in export_disputes(reviewed)))

    def test_save_confirms_resulting_values_without_repairing_source(self):
        original = saved(certificate_no='1'*19)
        field = next(f for f in original['fields'] if f['key'] == 'certificate_no')
        field['source'] = {'page': 1, 'raw_text': 'original OCR'}
        for patch, expected in [({}, '1'*19), ({'certificate_no': '2'*19}, '2'*19)]:
            with self.subTest(patch=patch):
                reviewed = apply_review(original, {'fields': patch, 'confirm_export_disputes': True}, actor='operator')
                self.assertFalse(export_disputes(reviewed))
                number = next(f for f in reviewed['fields'] if f['key'] == 'certificate_no')
                self.assertEqual(number['value'], expected)
                self.assertEqual(number['source'], field['source'])
                self.assertEqual(reviewed['_export_confirmations'][0]['actor'], 'operator')
                self.assertNotIn('_export_confirmations', public_result(reviewed))
                changed = apply_review(reviewed, {'fields': {'certificate_no': '3'*19}}, actor='operator')
                self.assertTrue(export_disputes(changed))
        self.assertEqual(field['value'], '1'*19)

    def test_save_cannot_waive_missing_or_unselected_conflict(self):
        original = saved(name=None, certificate_no='1'*19, school_name=None)
        school = next(f for f in original['fields'] if f['key'] == 'school_name')
        school['review_issues'] = [issue('CONFLICT', '两个候选未选择')]
        reviewed = apply_review(original, {'confirm_export_disputes': True}, actor='operator')
        self.assertEqual([d['field'] for d in export_disputes(reviewed)], ['school_name'])
        self.assertIn({'field': 'name', 'code': 'MISSING'}, required_export_blockers(reviewed))
        self.assertIn({'field': 'school_name', 'code': 'DISPUTED'}, required_export_blockers(reviewed))
        for invalid in ['true', 1, None]:
            with self.assertRaises(TaskError):
                apply_review(original, {'confirm_export_disputes': invalid}, actor='operator')
        with self.assertRaises(TaskError):
            apply_review({'doc_type': 'TABLE'}, {'confirm_export_disputes': True}, actor='operator')

    def test_lengths_share_warning_policy_and_never_modify_original(self):
        cases = [('INTERVIEW_FORM', 'id_number', '1'*19, True),
                 ('BANK_CARD', 'card_number', '621785123456789012', True),
                 ('BANK_CARD', 'card_number', '0000001234567890', False),
                 ('BANK_CARD', 'card_number', '6212410011234567', False),
                 ('DIPLOMA', 'certificate_no', '1'*19, True),
                 ('DIPLOMA', 'certificate_no', '1234', False),
                 ('DEGREE_CERT', 'certificate_no', 'T'+'1'*16, False),
                 ('DEGREE_CERT', 'certificate_no', '1'*17, True),
                 ('XUEXIN_DIPLOMA_TABLE', 'online_verification_code', 'A'*15, True)]
        for kind, key, value, warning in cases:
            with self.subTest(kind=kind, value=value):
                self.assertEqual(bool(number_length_warning(kind, key, value)), warning)
        result = saved(id_number='1'*19, certificate_no='1'*19)
        before = copy.deepcopy(result)
        self.assertIn({'field': 'certificate_no', 'code': 'DISPUTED'}, required_export_blockers(result))
        self.assertEqual(result, before)

    def test_information_does_not_block_and_checks_are_recomputed_for_legacy_results(self):
        result = saved()
        result['review_issues'] = [issue(code, '信息') for code in ['UNKNOWN', 'INCOMPLETE_OUTPUT', 'CONFIDENCE_UNAVAILABLE']]
        self.assertFalse(export_disputes(result))
        field = next(f for f in result['fields'] if f['key'] == 'graduate_date')
        field['value'] = '2020-99'
        field['validation_checks'] = []
        field['accepted_validation_rules'] = ['calendar_v1']
        self.assertEqual(export_disputes(result)[0]['field'], 'graduate_date')

    def test_confirmation_no_reason_preserves_evidence_and_expires_on_change(self):
        result = saved(certificate_no='1'*19)
        field = next(f for f in result['fields'] if f['key'] == 'certificate_no')
        field['source'] = {'raw_text': 'original OCR value', 'page': 1}
        original = copy.deepcopy(result)
        ids = [d['dispute_id'] for d in export_disputes(result)]
        confirmed = apply_review(result, {'confirmed_disputes': ids}, actor='operator')
        self.assertFalse(export_disputes(confirmed))
        self.assertEqual(result, original)
        self.assertEqual(confirmed['fields'], original['fields'])
        self.assertEqual(confirmed['_export_confirmations'][0]['actor'], 'operator')
        self.assertNotIn('_export_confirmations', public_result(confirmed))
        again = apply_review(confirmed, {}, actor='operator')
        self.assertFalse(export_disputes(again))
        changed = apply_review(again, {'fields': {'certificate_no': '2'*19}}, actor='operator')
        self.assertTrue(export_disputes(changed))
        restored = apply_review(changed, {'fields': {'certificate_no': '1'*19}}, actor='operator')
        self.assertTrue(export_disputes(restored))
        self.assertEqual(next(f for f in restored['fields'] if f['key'] == 'certificate_no')['source'], field['source'])
        rerun = copy.deepcopy(confirmed); rerun['run_id'] = str(uuid4())
        self.assertTrue(export_disputes(rerun))

    def test_no_implicit_acceptance_or_mixed_confirmation_and_edit(self):
        result = saved(graduate_date='2020-99')
        updated = apply_review(result, {}, actor='operator')
        target = next(f for f in updated['fields'] if f['key'] == 'graduate_date')
        problem = next(p for p in target['review_issues'] if p['code'] == 'VALIDATION_FAILED')
        with self.assertRaises(TaskError):
            apply_review(updated, {'accepted_issues': [{'issue_id': problem['issue_id']}]}, actor='operator')
        identifiers = [d['dispute_id'] for d in export_disputes(updated)]
        with self.assertRaises(TaskError):
            apply_review(updated, {'confirmed_disputes': identifiers, 'fields': {'name': '改名'}}, actor='operator')
        for ids in [identifiers*2, ['d_'+'0'*64], [1]]:
            with self.assertRaises(TaskError):
                apply_review(updated, {'confirmed_disputes': ids}, actor='operator')

    def test_conflict_cannot_disappear_on_same_value_patch(self):
        result = saved()
        field = next(f for f in result['fields'] if f['key'] == 'school_name')
        field['review_issues'] = [issue('CONFLICT', '两个识别结果不一致')]
        identifiers = [d['dispute_id'] for d in export_disputes(result)]
        again = apply_review(result, {'fields': {'school_name': field['value']}}, actor='operator')
        self.assertEqual(identifiers, [d['dispute_id'] for d in export_disputes(again)])
        field['value'] = None
        self.assertFalse(export_disputes(result)[0]['can_confirm'])
        self.assertIn({'field': 'school_name', 'code': 'MISSING'}, required_export_blockers(result))

    def test_missing_still_blocks_after_exception_confirmation(self):
        result = saved(name=None, certificate_no='1'*19)
        confirmed = apply_review(result, {'confirmed_disputes': [d['dispute_id'] for d in export_disputes(result)]}, actor='operator')
        self.assertEqual(required_export_blockers(confirmed), [{'field': 'name', 'code': 'MISSING'}])

    def test_cross_field_check_and_member_paths(self):
        result = saved('ID_CARD_FRONT', gender='M', birth_date='1949-12-31')
        conflict = next(d for d in export_disputes(result) if d['code'] == 'CONFLICT')
        confirmed = apply_review(result, {'confirmed_disputes': [conflict['dispute_id']]}, actor='operator')
        self.assertFalse(any(d['code'] == 'CONFLICT' for d in export_disputes(confirmed)))
        changed = apply_review(confirmed, {'fields': {'birth_date': '2000-01-01'}}, actor='operator')
        self.assertTrue(any(d['code'] == 'CONFLICT' for d in export_disputes(changed)))
        household = saved('HOUSEHOLD_REGISTER')
        household['members'] = [{'id_number': {'key': 'id_number', 'value': '1'*19}}]
        self.assertEqual(export_disputes(household)[0]['field'], 'members[0].id_number')

    def test_medical_exclusions_and_table_gate_are_unchanged(self):
        result = saved('MEDICAL_REPORT')
        result['items'] = [dict(name=name, result_raw='x', review_issues=[issue('CONFLICT', '冲突')])
                           for name in ['身高', '体重', '小结', '体重指数']]
        disputes = export_disputes(result)
        self.assertEqual([d['field'] for d in disputes], ['items[3]'])
        self.assertEqual(export_disputes(dict(doc_type='TABLE')), [])


class DisputeHTTPTests(unittest.TestCase):
    setUp = business_tests.BusinessAPITests.setUp
    upload = business_tests.BusinessAPITests.upload

    def test_result_detail_analyzes_disputes_once_and_matches_task_gate(self):
        from unittest.mock import patch
        created = self.upload().json()
        self.business.store.publish(self.business.store.claim_next(), saved(certificate_no='1'*19))
        task = self.business.store.tasks(created['batch_id'])[0]
        with patch('ocr_app.export_disputes.export_disputes', wraps=export_disputes) as analyze:
            detail = self.business.store.result(task['task_id'])
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(detail['export_ready'], task['export_ready'])
        self.assertEqual(detail['export_blockers'], task['export_blockers'])
        self.assertEqual(detail['export_disputes'][0]['field'], 'certificate_no')

    def test_bank_task_api_does_not_project_empty_result_fields(self):
        created = self.upload('BANK_CARD').json()
        self.business.store.publish(self.business.store.claim_next(), saved('BANK_CARD'))
        url = '/api/v1/tasks/' + created['task_ids'][0]
        first = self.client.get(url, headers=self.headers)
        second = self.client.get(url, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertNotIn('fields', first.json())
        self.assertEqual(first.json(), second.json())

    def test_unselected_medical_finding_blocks_until_result_is_chosen(self):
        created = self.upload('MEDICAL_REPORT').json()
        self.business.store.publish(self.business.store.claim_next(), ambiguous_medical_result())
        task = self.business.store.tasks(created['batch_id'])[0]
        current = self.business.store.result(task['task_id'])
        finding = current['report_summary']['findings'][0]
        self.assertIsNone(finding['result_item_id'])
        self.assertIsNone(finding['result_raw'])
        self.assertTrue(current['export_disputes'])
        self.assertFalse(current['export_disputes'][0]['can_confirm'])
        url = '/api/v1/tasks/' + task['task_id'] + '/review'
        version = dict(run_id=task['run_id'], expected_revision=task['result_revision'])
        rejected = self.client.post(url, headers=self.headers, json=dict(version,
            confirmed_disputes=[d['dispute_id'] for d in current['export_disputes']]))
        self.assertEqual(rejected.status_code, 422, rejected.text)
        saved_response = self.client.post(url, headers=self.headers,
            json=dict(version, confirm_export_disputes=True))
        self.assertEqual(saved_response.status_code, 200, saved_response.text)
        self.assertFalse(saved_response.json()['export_ready'])
        exported = self.client.post('/api/v1/export', headers=self.headers,
                                    json={'batch_id': created['batch_id']})
        self.assertEqual(exported.status_code, 409, exported.text)
        current = self.business.store.result(task['task_id'])
        selected = next(item for item in current['items'] if item['result_raw'] == '8.2')
        reviewed = self.client.post(url, headers=self.headers, json=dict(
            run_id=task['run_id'], expected_revision=saved_response.json()['result_revision'],
            findings=[dict(finding_id=finding['finding_id'], result_item_id=selected['item_id'])],
            confirm_export_disputes=True))
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertTrue(reviewed.json()['export_ready'])
        final = self.business.store.result(task['task_id'])
        self.assertEqual(final['report_summary']['findings'][0]['result_raw'], '8.2')
        self.assertEqual(final['generic'], current['generic'])
        self.assertEqual(self.client.post('/api/v1/export', headers=self.headers,
            json={'batch_id': created['batch_id']}).status_code, 200)

    def test_failed_result_can_confirm_exception_without_claiming_coverage_or_rewriting_error(self):
        created = self.upload().json()
        worker = self.business.store.claim_next()
        result = saved(certificate_no='1'*19)
        result.update(status='FAILED', error={'code':'EXTRACT_TIMEOUT','message':'synthetic timeout'})
        self.business.store.publish(worker, result)
        task = self.business.store.task(created['task_ids'][0])
        from sqlalchemy import text
        # Simulate recovery: row FAILED while the saved partial snapshot still
        # carries its earlier recognition status.
        with self.business.store.transaction() as connection:
            row = self.business.store._row(connection, task['task_id'])
            partial = self.business.storage.unpack(row['result_enc'])
            partial['status'] = 'NEED_REVIEW'
            connection.execute(text('UPDATE tasks SET result_enc=:result WHERE id=:id'),
                               dict(id=task['task_id'], result=self.business.storage.pack(partial)))
        current = self.business.store.result(task['task_id'])
        response = self.client.post('/api/v1/tasks/'+task['task_id']+'/review', headers=self.headers,
            json=dict(run_id=task['run_id'],expected_revision=task['result_revision'],
                      confirm_export_disputes=True))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'FAILED')
        self.assertEqual(response.json()['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertTrue(response.json()['export_ready'])
        self.assertNotIn('coverage_review', self.business.store.result(task['task_id']))

    def test_dispute_confirmation_keeps_ownership_fence(self):
        from test_batch_ownership import BatchOwnershipTests
        self.password = 'synthetic account password'
        _, owner_headers, _ = BatchOwnershipTests.account(self, 'owner')
        _, other_headers, _ = BatchOwnershipTests.account(self, 'other')
        created = self.upload(headers=owner_headers).json()
        worker = self.business.store.claim_next()
        self.business.store.publish(worker, saved(certificate_no='1'*19))
        task = self.business.store.task(created['task_ids'][0])
        current = self.business.store.result(task['task_id'])
        body = dict(run_id=task['run_id'], expected_revision=task['result_revision'],
                    confirm_export_disputes=True)
        url = '/api/v1/tasks/'+task['task_id']+'/review'
        self.assertEqual(self.client.post(url, headers=other_headers, json=body).status_code, 404)
        self.assertEqual(self.business.store.task(task['task_id'])['result_revision'], task['result_revision'])
        self.assertEqual(self.client.post(url, headers=owner_headers, json=body).status_code, 200)

    def prepare(self):
        import io
        from PIL import Image
        buffer = io.BytesIO(); Image.new('RGB', (20, 12), 'gray').save(buffer, format='PNG')
        created = self.client.post('/api/v1/batches', headers=self.headers,
            data={'doc_type_hint': 'DIPLOMA', 'person_name': '测试人员'},
            files=[('files', ('one.png', self.image, 'image/png')), ('files', ('two.png', buffer.getvalue(), 'image/png'))]).json()
        for index in range(2):
            worker = self.business.store.claim_next()
            self.business.store.publish(worker, saved(certificate_no='1'*(19 if index else 18)))
        return created

    def test_save_acknowledges_new_value_atomically_and_fences_stale_revision(self):
        created = self.prepare()
        bad = next(t for t in self.business.store.tasks(created['batch_id']) if not t['export_ready'])
        url = '/api/v1/tasks/'+bad['task_id']+'/review'
        body = dict(run_id=bad['run_id'], expected_revision=bad['result_revision'],
                    fields={'certificate_no': '2'*19}, confirm_export_disputes=True)
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        invalid = dict(body, confirm_export_disputes='true')
        self.assertEqual(self.client.post(url, headers=self.headers, json=invalid).status_code, 422)
        response = self.client.post(url, headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['export_ready'])
        self.assertEqual(response.json()['result_revision'], bad['result_revision']+1)
        self.assertEqual(self.client.post(url, headers=self.headers, json=body).status_code, 409)
        current = self.business.store.result(bad['task_id'])
        self.assertEqual(next(f for f in current['fields'] if f['key']=='certificate_no')['value'], '2'*19)
        self.assertEqual(current['export_disputes'], [])
        self.assertEqual(self.client.post('/api/v1/export', headers=self.headers,
                                        json={'batch_id': created['batch_id']}).status_code, 200)

    def test_atomic_export_detail_confirmation_version_and_private_audit(self):
        created = self.prepare()
        tasks = self.business.store.tasks(created['batch_id'])
        bad = next(t for t in tasks if not t['export_ready'])
        good = next(t for t in tasks if t['export_ready'])
        for request in [{'batch_id': created['batch_id']}, {'task_ids': created['task_ids']}, {'task_ids': [bad['task_id']]}]:
            response = self.client.post('/api/v1/export', headers=self.headers, json=request)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['details']['tasks'][0]['blockers'], [{'field': 'certificate_no', 'code': 'DISPUTED'}])
            self.assertNotIn('1'*19, response.text)
        self.assertEqual(self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [good['task_id']]}).status_code, 200)
        result = self.business.store.result(bad['task_id'])
        body = dict(run_id=bad['run_id'], expected_revision=bad['result_revision'], confirmed_disputes=[d['dispute_id'] for d in result['export_disputes']])
        url = '/api/v1/tasks/'+bad['task_id']+'/review'
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        response = self.client.post(url, headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['export_ready'])
        self.assertEqual(self.client.post(url, headers=self.headers, json=body).status_code, 409)
        self.assertEqual(self.client.post('/api/v1/export', headers=self.headers, json={'batch_id': created['batch_id']}).status_code, 200)
        current = self.business.store.result(bad['task_id'])
        self.assertFalse(current['export_disputes'])
        self.assertEqual(result['fields'], current['fields'])
        self.assertNotIn('_export_confirmations', current)
        with self.business.engine.connect() as connection:
            row = self.business.store._row(connection, bad['task_id'])
            raw = self.business.storage.unpack(row['result_enc'])
            self.assertTrue(raw['_export_confirmations'][0]['actor'])
            self.assertTrue(raw['_export_confirmations'][0]['confirmed_at'])


if __name__ == '__main__':
    unittest.main()
