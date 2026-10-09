import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from ocr_app.privacy import sensitive_patterns
from ocr_app.task_store import masked


def field(key,value,**extra): return dict(key=key,value=value,**extra)


class DocumentPrivacyTests(unittest.TestCase):
    def mask(self,value):return masked(value,sensitive_patterns(value))

    def test_passport_and_alphanumeric_code_mask_every_copy(self):
        result=dict(doc_type='PASSPORT',fields=[field('passport_number','E12345678'),field('online_verification_code','AB12 CD34 EF56 GH78')],
            generic=dict(full_text='E12345678 AB12CD34EF56GH78',blocks=[dict(text='Ｅ１２３４５６７８ AB12-CD34-EF56-GH78')]),
            items=[dict(diagnosis='E 1 2 3 4 5 6 7 8')])
        original=copy.deepcopy(result);public=self.mask(result)
        self.assertEqual(result,original)
        self.assertEqual(public['fields'][0]['value'],'****5678')
        self.assertEqual(public['fields'][1]['value'],'****GH78')
        self.assertNotIn('E12345678',json.dumps(public))
        self.assertEqual(public['items'][0]['diagnosis'],'****5678')
        self.assertEqual(public['generic']['blocks'][0]['text'],'****5678 ****GH78')

    def test_members_candidates_and_source_even_if_display_already_masked(self):
        result=dict(doc_type='HOUSEHOLD_REGISTER',fields=[field('household_no','001234')],members=[dict(id_number=field('id_number',None,candidates=[dict(value='11010519491231002X')])),
            dict(passport_number=field('passport_number','****5678',source=dict(raw_text='护照号码：E12345678')))],
            raw='户号001234 与 00123456不同 E12345678 身份11010519491231002X',
            basic_info=dict(phone=field('phone','（+86）138 0000 0000')))
        out=self.mask(result)
        self.assertEqual(out['fields'][0]['value'],'****1234')
        self.assertIn('00123456',out['raw'])
        self.assertNotIn('E12345678',out['raw'])
        self.assertEqual(out['basic_info']['phone']['value'],'****0000')
        self.assertNotIn('11010519491231002X',out['members'][0]['id_number']['candidates'][0]['value'])

    def test_unrelated_values_and_metadata_remain(self):
        uid='00012345-0001-4000-8000-000000000001'
        result=dict(doc_type='HOUSEHOLD_REGISTER',fields=[field('household_no','0001'),field('phone','2026-10-08'),field('report_no','1.23')],
            task_id=uid,content_hash='0'*60+'0001',source_sha256='a'*40+'1234567890123456789'+'b'*5,raw='1.23 2026-10-08 X0001Y 10001 13812345678')
        out=self.mask(result)
        self.assertEqual(out['task_id'],uid)
        self.assertEqual(out['content_hash'],result['content_hash'])
        self.assertEqual(out['source_sha256'],result['source_sha256'])
        self.assertEqual(out['raw'],result['raw'])

    def test_words_are_not_identifier_substrings(self):
        result=dict(doc_type='PASSPORT',fields=[field('passport_number','E12345678')],raw='XE12345678Y E123456789 E12345678')
        self.assertEqual(self.mask(result)['raw'],'XE12345678Y E123456789 ****5678')

    def test_short_identifier_does_not_remask_a_long_identifier_suffix(self):
        result=dict(fields=[field('household_no','0001'),field('phone','13900000001')],raw='13900000001;0001')
        self.assertEqual(self.mask(result)['raw'],'****0001;****')

    def test_unknown_values_do_not_authorize_short_global_masking(self):
        result=dict(doc_type='GENERIC',fields=[field('household_no','12'),field('certificate_no','TEST'),field('phone','1.23')],generic=dict(full_text='12 TEST 1.23 E12345678'))
        self.assertEqual(sensitive_patterns(result),[])

    def test_business_uscc_does_not_seed_general_sensitive_rules(self):
        result=dict(doc_type='BUSINESS_LICENSE',fields=[field('unified_social_credit_code','91350100M000100Y43'),field('passport_number','E12345678')])
        rules=sensitive_patterns(result)
        self.assertTrue(rules)
        self.assertTrue(all(p.search('91350100M000100Y43') is None for p,_ in rules))

    def test_current_public_projection_returns_full_values(self):
        from ocr_app.task_store import public_result
        value=dict(doc_type='BUSINESS_LICENSE',fields=[field('unified_social_credit_code','911100001000000000'),
            field('passport_number','E12345678')],generic=dict(full_text='私人护照E12345678'))
        out=public_result(value)
        self.assertEqual(out['fields'][0]['value'],'911100001000000000')
        self.assertEqual(out['fields'][1]['value'],'E12345678')
        self.assertEqual(out['generic']['full_text'],'私人护照E12345678')

    def test_sensitive_history_masks_original_after_human_correction(self):
        result=dict(fields=[field('passport_number','E87654321',_sensitive_history=['E12345678'])],generic=dict(full_text='E12345678 E87654321'))
        self.assertEqual(self.mask(result)['generic']['full_text'],'****5678 ****4321')

    def test_public_bank_projection_omits_legacy_derived_mask_without_mutation(self):
        from ocr_app.task_store import public_result
        value=dict(doc_type='BANK_CARD',fields=[field('card_number','0012345678901234',
            value_masked='****1234',_sensitive_history=['0098765432101234']),
            field('card_number_masked','****1234')])
        original=copy.deepcopy(value)
        out=public_result(value)
        self.assertEqual(value,original)
        self.assertEqual(len(out['fields']),1)
        self.assertEqual(out['fields'][0],field('card_number','0012345678901234'))


if __name__=='__main__':unittest.main()
