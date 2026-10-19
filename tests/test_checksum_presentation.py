"""Known legacy dispute fingerprints survive a purely editorial failure message."""
import copy
import unittest
from unittest.mock import patch

from sqlalchemy import text
import test_business_api as base

from ocr_app.export_disputes import export_disputes, retain_confirmations
from ocr_app.review import apply_review
from ocr_app.task_store import public_result
from ocr_app.validation import validate_field
from ocr_app.extraction import issue
from test_export_disputes import saved


LEGACY = '仅校验号码校验位。'
FAILURE = '末位校验位与计算结果不符，请对照原件核对；系统仅本地校验，不联网核验。'
FIELD_ID = 'd_ae6a93502cfda845fb06161a1861d267c081526f823e2e0afb51182ddd4b439f'
TASK_ID = 'd_beba605c03e299969c0a6c1b36fb4b27841bb7a992003d34bbea12e4adcc3488'


def legacy_result(top=False):
    result = saved('INTERVIEW_FORM', id_number='110105194912310021', gender='F')
    result['run_id'] = '11111111-2222-4333-8444-555555555555'
    field = next(f for f in result['fields'] if f['key'] == 'id_number')
    field['source'] = dict(raw_text=field['value'], page=1)
    field['validation_checks'] = [dict(kind='CHECKSUM', status='FAIL', rule_id='id_cn_v1', message=LEGACY)]
    field['review_issues'] = [issue('VALIDATION_FAILED', LEGACY)]
    if top:
        result['review_issues'] = [issue('VALIDATION_FAILED', LEGACY)]
    return result


def legacy_checks(*args, **kwargs):
    checks = validate_field(*args, **kwargs)
    for check in checks:
        if check['rule_id'] == 'id_cn_v1' and check['kind'] == 'CHECKSUM':
            check['message'] = LEGACY
    return checks


class ChecksumPresentationTests(unittest.TestCase):
    def test_failed_checksum_explains_failure_pass_and_values_stay_unchanged(self):
        for value, status, message in [('110105194912310021', 'FAIL', FAILURE), ('11010519491231002X', 'PASS', LEGACY)]:
            checks = validate_field('ID_CARD_FRONT', 'id_number', value)
            checksum = next(c for c in checks if c['kind'] == 'CHECKSUM')
            self.assertEqual((checksum['status'], checksum['message']), (status, message))

    def test_golden_legacy_ids_and_confirmations_survive_read_and_ordinary_save(self):
        for top in (False, True):
            result = legacy_result(top)
            expected = [TASK_ID, FIELD_ID] if top else [FIELD_ID]
            disputes = export_disputes(result)
            self.assertEqual([d['dispute_id'] for d in disputes], expected)
            self.assertTrue(all(d['message'] == FAILURE for d in disputes))
            result['_export_confirmations'] = [dict(dispute_id=i, actor='historical-operator',
                confirmed_at='2026-10-18T00:00:00Z') for i in expected]
            before = copy.deepcopy(result)
            response = public_result(result)
            self.assertNotIn('_export_confirmations', response)
            self.assertEqual(result, before)
            self.assertFalse(export_disputes(result))
            for patch_body in ({}, {'confirm_export_disputes': True}):
                reviewed = apply_review(result, patch_body, actor='current-operator')
                self.assertEqual(reviewed['_export_confirmations'], before['_export_confirmations'])
                self.assertFalse(export_disputes(reviewed))

    def test_legacy_public_failure_projection_is_a_copy_and_keeps_pass_messages(self):
        result = legacy_result(True)
        field = next(f for f in result['fields'] if f['key'] == 'id_number')
        field['validation_checks'].append(dict(kind='CHECKSUM', status='PASS', rule_id='id_cn_v1', message=LEGACY))
        before = copy.deepcopy(result)
        response = public_result(result)
        shown = next(f for f in response['fields'] if f['key'] == 'id_number')
        self.assertEqual([c['message'] for c in shown['validation_checks']], [FAILURE, LEGACY])
        self.assertEqual(shown['review_issues'][0]['message'], FAILURE)
        self.assertEqual(response['review_issues'][0]['message'], FAILURE)
        self.assertEqual(result, before)

    def test_value_source_and_run_changes_still_expire_confirmation(self):
        original = legacy_result()
        original['_export_confirmations'] = [dict(dispute_id=FIELD_ID, actor='historical', confirmed_at='2026-10-18')]
        for change in ('value', 'source', 'run'):
            result = copy.deepcopy(original)
            field = next(f for f in result['fields'] if f['key'] == 'id_number')
            if change == 'value': field['value'] = '110105194912310023'
            elif change == 'source': field['source']['raw_text'] = 'different synthetic evidence'
            else: result['run_id'] = '11111111-2222-4333-8444-555555555556'
            retain_confirmations(result)
            self.assertEqual(result['_export_confirmations'], [], change)
            self.assertTrue(export_disputes(result), change)

    def test_household_member_and_unrelated_issue_identities_remain_stable(self):
        result = saved('HOUSEHOLD_REGISTER')
        number = copy.deepcopy(next(f for f in legacy_result()['fields'] if f['key'] == 'id_number'))
        result['members'] = [{'fields': [number]}]
        result['review_issues'] = [issue('CONFLICT', 'unrelated synthetic issue')]
        with patch('ocr_app.export_disputes.validate_field', side_effect=legacy_checks):
            historical = export_disputes(result)
        result['_export_confirmations'] = [dict(dispute_id=d['dispute_id'], actor='old', confirmed_at='old') for d in historical]
        current = export_disputes(result, include_confirmed=True)
        self.assertEqual([d['dispute_id'] for d in current], [d['dispute_id'] for d in historical])
        self.assertEqual([d['message'] for d in current], ['unrelated synthetic issue', FAILURE])
        retain_confirmations(result)
        self.assertFalse(export_disputes(result))
        self.assertEqual(len(result['_export_confirmations']), 2)


class ChecksumHistoryHTTPTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    upload = base.BusinessAPITests.upload

    def test_legacy_encrypted_history_is_read_only_and_survives_export_and_noop_save(self):
        created = self.upload('INTERVIEW_FORM').json()
        store = self.business.store
        worker = store.claim_next()
        original = legacy_result(True)
        original['run_id'] = worker['run_id']
        with patch('ocr_app.export_disputes.validate_field', side_effect=legacy_checks):
            historical_ids = [d['dispute_id'] for d in export_disputes(original)]
        original['_export_confirmations'] = [dict(dispute_id=i, actor='historical-operator',
            confirmed_at='2026-10-18T00:00:00Z') for i in historical_ids]
        self.assertTrue(store.publish(worker, original))
        identifier = created['task_ids'][0]
        with self.business.engine.connect() as c:
            before = c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'), dict(id=identifier)).scalar_one()
            run_before = dict(c.execute(text('SELECT * FROM runs WHERE id=:id'), dict(id=worker['run_id'])).mappings().one())
        url = '/api/v1/tasks/' + identifier
        for suffix in ('', '/result'):
            response = self.client.get(url + suffix, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['export_ready'])
        detail = self.client.get(url + '/result', headers=self.headers).json()
        number = next(f for f in detail['fields'] if f['key'] == 'id_number')
        self.assertEqual(number['value'], '110105194912310021')
        self.assertEqual(number['validation_checks'][0]['message'], FAILURE)
        self.assertEqual(number['source'], next(f for f in original['fields'] if f['key'] == 'id_number')['source'])
        self.assertEqual(detail['export_disputes'], [])
        self.assertNotIn('_export_confirmations', detail)
        exported = self.client.post('/api/v1/export', headers=self.headers, json=dict(batch_id=created['batch_id']))
        self.assertEqual(exported.status_code, 200, exported.text[:100] if exported.status_code != 200 else '')
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'), dict(id=identifier)).scalar_one(), before)
        saved_response = self.client.post(url + '/review', headers=self.headers,
            json=dict(run_id=detail['run_id'], expected_revision=detail['result_revision'], confirm_export_disputes=True))
        self.assertEqual(saved_response.status_code, 200, saved_response.text)
        self.assertTrue(saved_response.json()['export_ready'])
        with self.business.engine.connect() as c:
            after = self.business.storage.unpack(c.execute(text('SELECT result_enc FROM tasks WHERE id=:id'), dict(id=identifier)).scalar_one())
            self.assertEqual(dict(c.execute(text('SELECT * FROM runs WHERE id=:id'), dict(id=worker['run_id'])).mappings().one()), run_before)
        self.assertEqual(after['_export_confirmations'], original['_export_confirmations'])
        self.assertFalse(export_disputes(after))


if __name__ == '__main__':
    unittest.main()
