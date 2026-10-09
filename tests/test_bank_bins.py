"""Offline prefix inference never claims issuer/account authenticity."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from ocr_app.bank_bins import lookup_bank
from ocr_app.extraction import extract_result
from ocr_app.review import apply_review
from ocr_app.validation import validate_field

ROWS=[dict(bin='123456',bank='A',type='DC',length='16'),dict(bin='12345678',bank='B',type='CC',length='16'),dict(bin='654321',bank='C',type='DC',length='16')]
NAMES={'A':'合成甲银行','B':'合成乙银行','C':'合成丙银行'}

def fields(result):return {f['key']:f for f in result['fields']}
def sample(number='1234567890123456'):
    return extract_result([dict(text=number,page=1,region_id=str(uuid4()),bbox=[0,0,1,1],extraction_method='ocr')],'BANK_CARD')

class BankBinTests(unittest.TestCase):
    def setUp(self):self.fixture=patch('ocr_app.bank_bins._data',return_value=(ROWS,NAMES));self.fixture.start();self.addCleanup(self.fixture.stop)

    def test_longest_prefix_and_unknown(self):
        match=lookup_bank('１２３４ ５６７８ ９０１２ ３４５６')
        self.assertEqual((match['status'],match['prefix'],match['bank_name'],match['card_type']),('MATCHED','12345678','合成乙银行','CC'))
        self.assertEqual(lookup_bank('9999990000000000')['status'],'UNKNOWN')
        self.assertEqual(lookup_bank('not a number')['reason_code'],'INVALID_PAN')

    def test_longer_unsupported_prefix_and_length_mismatch_never_fall_back(self):
        for extra in [dict(bin='123456789',bank='C',type='DC',length='16'),dict(bin='123456789',bank='C',type='DC',length='19')]:
            with patch('ocr_app.bank_bins._data',return_value=(ROWS+[extra],NAMES)):
                self.assertEqual(lookup_bank('1234567890123456')['reason_code'],'UNSUPPORTED_PREFIX_LENGTH')
        rows=[ROWS[0],dict(ROWS[1],length='19')]
        with patch('ocr_app.bank_bins._data',return_value=(rows,NAMES)):
            self.assertEqual(lookup_bank('1234567890123456')['reason_code'],'PAN_LENGTH_MISMATCH')

    def test_same_specificity_conflict_abstains(self):
        with patch('ocr_app.bank_bins._data',return_value=(ROWS+[dict(ROWS[1],bank='C')],NAMES)):
            self.assertEqual(lookup_bank('1234567890123456')['status'],'CONFLICT')

    def test_derived_values_do_not_forge_ocr_sources(self):
        result=sample();f=fields(result)
        self.assertEqual(f['bank_name']['value'],'合成乙银行')
        for key in ['bank_name','bin_code','card_type']:
            self.assertEqual(f[key]['value_origin'],'derived')
            self.assertEqual(f[key]['derivation']['input_field'],'card_number')
            self.assertEqual(f[key]['derivation']['method'],'offline_bin')
            self.assertNotIn('source',f[key]);self.assertIsNone(f[key]['confidence'])
        self.assertEqual(f['card_number']['source']['raw_text'],'1234567890123456')
        self.assertIsNone(f['card_scheme']['value'])
        checks=validate_field('BANK_CARD','card_number',f['card_number']['value'])
        self.assertTrue(any(c['rule_id']=='bin_snapshot_v1' and c['status']=='PASS' for c in checks))
        self.assertTrue(all(c['status']=='UNKNOWN' for c in checks if c['kind'] in {'CHECKSUM','OFFICIAL'}))

    def test_pan_correction_recomputes_then_clears_unknown(self):
        original=sample();raw=fields(original)['card_number']['source'].copy()
        fixed=apply_review(original,{'fields':{'card_number':'6543210000000000'}},actor='test')
        self.assertEqual(fields(fixed)['bank_name']['value'],'合成丙银行')
        self.assertEqual(fields(fixed)['card_number']['source'],raw)
        unknown=apply_review(fixed,{'fields':{'card_number':'9999990000000000'}},actor='test')
        for key in ['bank_name','bin_code','card_type']:
            self.assertIsNone(fields(unknown)[key]['value']);self.assertNotIn('derivation',fields(unknown)[key])
        self.assertEqual(fields(original)['bank_name']['value'],'合成乙银行')

    def test_manual_name_is_preserved_reviewable_and_acceptance_survives(self):
        manual=apply_review(sample(),{'fields':{'bank_name':'原件银行名称'}},actor='test')
        bank=fields(manual)['bank_name']
        self.assertEqual(bank['value'],'原件银行名称');self.assertEqual(bank['value_origin'],'manual');self.assertNotIn('derivation',bank)
        mismatch=next(i for i in bank['review_issues'] if i.get('rule_id')=='bin_reference_bank_name_v1')
        self.assertEqual(mismatch['code'],'VALIDATION_FAILED');self.assertTrue(mismatch['can_accept'])
        accepted=apply_review(manual,{'accepted_issues':[{'issue_id':mismatch['issue_id']}]},actor='test')
        self.assertFalse(fields(accepted)['bank_name']['need_review'])
        unchanged=apply_review(accepted,{},actor='test')
        self.assertFalse(fields(unchanged)['bank_name']['need_review'])
        changed=apply_review(accepted,{'fields':{'card_number':'6543210000000000'}},actor='test')
        self.assertEqual(fields(changed)['bank_name']['value'],'原件银行名称')
        self.assertTrue(fields(changed)['bank_name']['need_review'])

    def test_completed_card_revalidation_is_idempotent_then_new_pan_reopens_manual_check(self):
        manual=apply_review(sample(),{'fields':{'bank_name':'原件银行名称'}},actor='test')
        accepted=[{'issue_id':p['issue_id']} for f in manual['fields'] for p in f['review_issues'] if p['can_accept']]
        complete=apply_review(manual,{'accepted_issues':accepted},actor='test')
        self.assertEqual(complete['status'],'COMPLETED')
        repeat=apply_review(complete,{},actor='export-check')
        self.assertEqual(repeat['status'],'COMPLETED')
        for key in ['bank_name','bin_code','card_type']:
            self.assertEqual(fields(repeat)[key],fields(complete)[key])
        new_pan=apply_review(repeat,{'fields':{'card_number':'6543210000000000'}},actor='test')
        self.assertEqual(new_pan['status'],'NEED_REVIEW')
        self.assertTrue(any(p.get('rule_id')=='bin_reference_bank_name_v1' for p in fields(new_pan)['bank_name']['review_issues']))
        self.assertNotIn('bin_reference_bank_name_v1',fields(new_pan)['bank_name'].get('accepted_validation_rules',[]))

    def test_bin_code_is_readonly_and_bad_data_is_unknown(self):
        from ocr_app.task_store import TaskError
        with self.assertRaises(TaskError):apply_review(sample(),{'fields':{'bin_code':'999999'}},actor='test')
        with patch('ocr_app.bank_bins._data',side_effect=ValueError('BIN_DATA_HASH_MISMATCH')):
            self.assertEqual(lookup_bank('1234567890123456')['reason_code'],'DATA_UNAVAILABLE')

    def test_invalid_manual_pan_is_blocking_and_cannot_be_accepted(self):
        from ocr_app.task_store import TaskError
        for number in ['not-a-number', '123456789', '1' * 20]:
            with self.subTest(number=number):
                result=apply_review(extract_result([], 'BANK_CARD'), {'fields': {'card_number': number}}, actor='test')
                self.assertEqual(result['status'], 'NEED_REVIEW')
                card=fields(result)['card_number']
                self.assertTrue(any(c['rule_id']=='pan_compat_v1' and c['status']=='FAIL' for c in card['validation_checks']))
                problem=next(p for p in card['review_issues'] if p.get('rule_id')=='pan_compat_v1')
                self.assertFalse(problem['can_accept'])
                with self.assertRaises(TaskError):
                    apply_review(result, {'accepted_issues': [{'issue_id': problem['issue_id']}]}, actor='test')
                self.assertEqual(apply_review(result, {}, actor='export-check')['status'], 'NEED_REVIEW')
                corrected=apply_review(result, {'fields': {'card_number': '9999990000000000'}}, actor='test')
                self.assertFalse(any(p.get('rule_id')=='pan_compat_v1' for p in fields(corrected)['card_number']['review_issues']))

    def test_valid_unknown_pan_can_be_explicitly_confirmed(self):
        result=sample('9999990000000000')
        accepted=[{'issue_id': p['issue_id']} for f in result['fields'] for p in f['review_issues'] if p['can_accept']]
        confirmed=apply_review(result, {'accepted_issues': accepted}, actor='test')
        self.assertEqual(confirmed['status'], 'COMPLETED')
        self.assertEqual(apply_review(confirmed, {}, actor='export-check')['status'], 'COMPLETED')
        checks=fields(confirmed)['card_number']['validation_checks']
        self.assertTrue(any(c['rule_id']=='bin_snapshot_v1' and c['status']=='UNKNOWN' for c in checks))
        self.assertTrue(any(c['kind']=='CHECKSUM' and c['status']=='UNKNOWN' for c in checks))

    def test_explicit_candidate_conflict_is_not_replaced_by_lookup(self):
        result=extract_result([dict(text='1234567890123456\n发卡行：原文甲\n发卡行：原文乙',page=1,region_id=str(uuid4()),extraction_method='ocr')],'BANK_CARD')
        bank=fields(result)['bank_name']
        self.assertIsNone(bank['value']);self.assertEqual(len(bank['candidates']),2)
        self.assertTrue(any(i['code']=='CONFLICT' and not i['can_accept'] for i in bank['review_issues']))
        self.assertNotIn('derivation',bank)

class InvalidPanHTTPTests(unittest.TestCase):
    def setUp(self):
        import test_business_api
        test_business_api.BusinessAPITests.setUp(self)

    def test_invalid_pan_stays_unreviewed_but_present_value_can_export(self):
        import hashlib
        safe=dict(data=self.image, name='synthetic-card.png', mime='image/png', actual_source_page_count=1,
                  processed_content_hash=hashlib.sha256(self.image).hexdigest(),
                  admission=dict(text='9999990000000000', normalized='9999990000000000', termination_reason='eos'))
        store=self.business.store
        for number in ['not-a-number', '123456789', '1' * 20]:
            with self.subTest(number=number):
                identifier=store.create_batch([safe], 'BANK_CARD', 'synthetic')['task_ids'][0]
                worker=store.claim_next()
                self.assertTrue(store.publish(worker, extract_result([], 'BANK_CARD')))
                url=f'/api/v1/tasks/{identifier}'
                task=self.client.get(url, headers=self.headers).json()
                body=dict(run_id=task['run_id'], expected_revision=task['result_revision'], fields={'card_number': number})
                response=self.client.post(url+'/review', headers=self.headers, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], 'NEED_REVIEW')
                exported=self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [identifier]})
                self.assertEqual(exported.status_code, 200)
                self.assertEqual(self.client.get(url, headers=self.headers).json()['status'], 'NEED_REVIEW')
                latest=response.json()
                body.update(expected_revision=latest['result_revision'], fields={'card_number': '9999990000000000'})
                corrected=self.client.post(url+'/review', headers=self.headers, json=body)
                self.assertEqual(corrected.status_code, 200, corrected.text)
                self.assertEqual(corrected.json()['status'], 'COMPLETED')
                self.assertEqual(self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [identifier]}).status_code, 200)

if __name__=='__main__':unittest.main()
