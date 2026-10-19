import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.doc_profiles import catalogue, profile
from ocr_app.validation import validate_field
from ocr_app.document_fields import extract_document_fields, _normalize


def evidence(text, page=1, **extra):
    return dict(text=text, page=page, region_id=f'p{page}', bbox=[0, 0, 1, 1], extraction_method='pdf_text', **extra)


class DocumentProfileTests(unittest.TestCase):
    def test_catalogue_and_legacy_counts(self):
        self.assertEqual(len(catalogue()), 14)
        for kind, count in [('DIPLOMA', 11), ('DEGREE_CERT', 10), ('MEDICAL_REPORT', 17)]:
            self.assertEqual(len(profile(kind)), count)
        self.assertNotIn('card_number_masked',{x['key'] for x in profile('BANK_CARD')})

    def test_conditional_fields(self):
        self.assertFalse(next(x for x in profile('BUSINESS_LICENSE', {'company_type':'个体工商户'}) if x['key']=='registered_capital')['required'])
        self.assertFalse(next(x for x in profile('HOUSEHOLD_REGISTER', {'household_type':'集体户口'}) if x['key']=='householder')['required'])

    def test_id_checksum_and_cross_fields(self):
        checks=validate_field('ID_CARD_FRONT','id_number','11010519491231002X',{'birth_date':'1949-12-31','gender':'F'})
        self.assertIn(('CHECKSUM','PASS'),[(c['kind'],c['status']) for c in checks])
        self.assertIn('FAIL',[c['status'] for c in validate_field('ID_CARD_FRONT','id_number','110105194912310021')])
        self.assertIn('FAIL',[c['status'] for c in validate_field('ID_CARD_FRONT','id_number','11010519491231002X',{'gender':'M'})])

    def test_dates_and_unknown_bank(self):
        self.assertEqual(validate_field('DIPLOMA','birth_date','2023-02-29')[0]['status'],'FAIL')
        checks=validate_field('BANK_CARD','card_number','4111111111111111')
        self.assertIn(('CHECKSUM','UNKNOWN'),[(c['kind'],c['status']) for c in checks])
        self.assertTrue(any(c['status']=='UNKNOWN' and 'bin' in c['rule_id'] for c in checks))
        self.assertEqual(validate_field('DEGREE_CERT','degree_category','学士')[0]['status'],'PASS')
        self.assertEqual(validate_field('XUEXIN_DIPLOMA_TABLE','education_level','研究生')[0]['status'],'UNKNOWN')

    def test_xuexin_code_is_not_official_verification(self):
        c=validate_field('XUEXIN_DIPLOMA_TABLE','online_verification_code','AB12 CD34 EF56 GH78')
        self.assertEqual(c[0]['status'],'PASS')
        self.assertTrue(any(x['kind']=='OFFICIAL' and x['status']=='UNKNOWN' for x in c))
        self.assertEqual(validate_field('XUEXIN_DIPLOMA_TABLE','online_verification_code','１２３４５６７８９０１２')[0]['status'],'UNKNOWN')

    def test_xuexin_kind_and_conflict(self):
        result=extract_document_fields([evidence('教育部学历证书电子注册备案表\n姓名：测试甲\n学校名称：测试大学\n在线验证码：AB12 CD34 EF56 GH78'),evidence('姓名：测试乙',2)],'XUEXIN_DIPLOMA_TABLE')
        self.assertEqual(result['xuexin_info']['report_kind'],'DIPLOMA_TABLE')
        self.assertIsNone(next(f for f in result['fields'] if f['key']=='name')['value'])
        other=extract_document_fields([evidence('教育部学籍在线验证报告\n姓名：测试甲')],'XUEXIN_DIPLOMA_TABLE')
        self.assertEqual(other['xuexin_info']['report_kind'],'OTHER_REPORT')
        self.assertTrue(all(f['value'] is None for f in other['fields']))

    def test_duration_whitespace_equivalence_keeps_original_evidence(self):
        for spaced,compact in [('四 年','四年'),('二 点 五 年','二点五年'),('2 . 5 年','2.5年'),('３ 年','３年')]:
            with self.subTest(spaced=spaced):
                native=evidence('教育部学历证书电子注册备案表\n学制：'+spaced)
                ocr=evidence('学制：'+compact,2);ocr['extraction_method']='ocr'
                result=extract_document_fields([native,ocr],'XUEXIN_DIPLOMA_TABLE')
                field=next(f for f in result['fields'] if f['key']=='duration')
                self.assertEqual(field['value'],compact)
                self.assertEqual(field['source']['raw_text'],'学制：'+spaced)
                self.assertFalse(any(i['code']=='CONFLICT' for i in field['review_issues']))

    def test_duration_different_values_conflict_and_free_text_stays_verbatim(self):
        result=extract_document_fields([evidence('教育部学历证书电子注册备案表\n学制：四 年'),evidence('学制：五年',2)],'XUEXIN_DIPLOMA_TABLE')
        field=next(f for f in result['fields'] if f['key']=='duration')
        self.assertIsNone(field['value'])
        self.assertTrue(any(i['code']=='CONFLICT' for i in field['review_issues']))
        for original in ['弹性 学制','三 至 五 年','预计 四 年','4 年以上','4 year','十十 年']:
            self.assertEqual(_normalize('duration',original),original)

    def test_html_and_generic(self):
        out=extract_document_fields([evidence('<table><tr><td>姓名</td><td>测试甲</td><td>民族</td><td>汉</td></tr></table>')],'ID_CARD_FRONT')
        self.assertEqual(next(f for f in out['fields'] if f['key']=='name')['value'],'测试甲')
        generic=extract_document_fields([evidence('项目：测试内容')],'GENERIC')['generic']
        self.assertEqual(generic['key_values'][0]['value'],'测试内容')

    def test_identity_gender_and_ethnicity_in_one_value_stay_separate(self):
        for text, expected_gender, expected_ethnicity in [
            ('性别 男 民族汉', 'M', '汉'),
            ('性别：女 民 族维吾尔', 'F', '维吾尔'),
            ('性别 男 民族', 'M', None),
            ('<table><tr><td>性别</td><td>女 民族：汉</td></tr></table>', 'F', '汉'),
            ('性别：女\n民族：汉', 'F', '汉'),
        ]:
            with self.subTest(text=text):
                block = evidence(text)
                fields = {f['key']: f for f in extract_document_fields([block], 'ID_CARD_FRONT')['fields']}
                self.assertEqual(fields['gender']['value'], expected_gender)
                self.assertEqual(fields['ethnicity']['value'], expected_ethnicity)
                self.assertEqual(fields['gender']['source']['page'], block['page'])
                if expected_ethnicity:
                    self.assertIn('族', fields['ethnicity']['source']['raw_text'])

    def test_identity_demographic_split_keeps_conflicts_and_other_fields(self):
        blocks = [evidence('性别 男 民族汉\n住址：民族团结路'), evidence('民族：回', 2)]
        fields = {f['key']: f for f in extract_document_fields(blocks, 'ID_CARD_FRONT')['fields']}
        self.assertEqual(fields['gender']['value'], 'M')
        self.assertIsNone(fields['ethnicity']['value'])
        self.assertEqual({c['value'] for c in fields['ethnicity']['candidates']}, {'汉', '回'})
        self.assertEqual(fields['address']['value'], '民族团结路')
        self.assertTrue(any(i['code'] == 'CONFLICT' for i in fields['ethnicity']['review_issues']))
        passport = extract_document_fields([evidence('性别：男 民族汉')], 'PASSPORT')
        self.assertEqual(next(f for f in passport['fields'] if f['key'] == 'gender')['value'], '男 民族汉')

    def test_td3_no_century_guess(self):
        a='P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<'
        b='L898902C36UTO7408122F1204159ZE184226B<<<<<10'
        out=extract_document_fields([evidence(a+'\n'+b)],'PASSPORT')
        fields={f['key']:f['value'] for f in out['fields']}
        self.assertEqual(fields['passport_number'],'L898902C3')
        self.assertIsNone(fields['birth_date'])
        checks=validate_field('PASSPORT','mrz',a+'\n'+b)
        self.assertTrue(any(c['kind']=='CHECKSUM' and c['status']=='PASS' for c in checks))

    def test_bank_crop_preserves_raw_separators_without_issuer_guess(self):
        raw='4111-1111\u30001111 1111'
        out=extract_document_fields([evidence(raw)],'BANK_CARD')
        fields={f['key']:f for f in out['fields']}
        self.assertEqual(fields['card_number']['value'],'4111111111111111')
        self.assertEqual(fields['card_number']['source']['raw_text'],raw)
        self.assertIsNone(fields['bank_name']['value'])
        self.assertNotIn('card_number_masked',fields)

    def test_fullwidth_bank_crop_normalizes_value_but_keeps_source(self):
        raw='４１１１－１１１１　１１１１ １１１１'
        result=extract_document_fields([evidence(raw)],'BANK_CARD')
        item=next(f for f in result['fields'] if f['key']=='card_number')
        self.assertEqual(item['value'],'4111111111111111')
        self.assertEqual(item['source']['raw_text'],raw)
        self.assertTrue(all(i['code']!='FORMAT' for f in result['fields'] for i in f['review_issues']))

    def test_validation_review_issue_uses_contract_code(self):
        result=extract_document_fields([evidence('公民身份号码：110105194912310021')],'ID_CARD_FRONT')
        item=next(f for f in result['fields'] if f['key']=='id_number')
        self.assertTrue(any(i['code']=='VALIDATION_FAILED' for i in item['review_issues']))
        self.assertTrue(all(i['code']!='FORMAT' for i in item['review_issues']))

    def test_old_license_and_empty_generic_abstain(self):
        fields={f['key']:f for f in profile('BUSINESS_LICENSE',{'registration_no':'123456789012345'})}
        self.assertFalse(fields['unified_social_credit_code']['required'])
        self.assertTrue(fields['registration_no']['required'])
        out=extract_document_fields([], 'GENERIC')
        self.assertFalse(out['review_issues'][0]['can_accept'])

    def test_uscc_checksum_and_calendar(self):
        code='91350100M000100Y43'
        self.assertTrue(any(c['status']=='PASS' and c['kind']=='CHECKSUM' for c in validate_field('BUSINESS_LICENSE','unified_social_credit_code',code)))
        bad=code[:-1]+('1' if code[-1]!='1' else '2')
        self.assertTrue(any(c['status']=='FAIL' for c in validate_field('BUSINESS_LICENSE','unified_social_credit_code',bad)))

    def test_geometry_pairs_only_unique_same_page(self):
        a=evidence('姓 名');a['bbox']=[.1,.1,.3,.15]
        b=evidence('测试甲');b['bbox']=[.4,.1,.6,.15]
        f=extract_document_fields([a,b],'ID_CARD_FRONT')['fields'][0]
        self.assertEqual(f['value'],'测试甲')
        c=evidence('测试乙');c['bbox']=[.7,.1,.9,.15]
        self.assertIsNone(extract_document_fields([a,b,c],'ID_CARD_FRONT')['fields'][0]['value'])

    def test_id_back_date_range_and_order(self):
        out=extract_document_fields([evidence('签发机关：测试公安局\n有效期限 2020.01.02-长期')],'ID_CARD_BACK')
        values={f['key']:f['value'] for f in out['fields']}
        self.assertEqual(values['valid_from'],'2020-01-02')
        self.assertEqual(values['valid_to'],'长期')
        checks=validate_field('PASSPORT','expiry_date','2020-01-01',{'issue_date':'2021-01-01'})
        self.assertTrue(any(c['kind']=='CROSS_DOCUMENT' and c['status']=='FAIL' for c in checks))

    def test_household_members_remain_page_bound(self):
        es=[evidence('户别：集体户口\n户号：001\n住址：测试地址'),evidence('常住人口登记卡\n姓名：测试甲\n性别：男',2),evidence('常住人口登记卡\n姓名：测试乙\n性别：女',3)]
        out=extract_document_fields(es,'HOUSEHOLD_REGISTER')
        self.assertEqual(len(out['members']),2)
        self.assertEqual(out['members'][0]['name']['source']['page'],2)
        self.assertEqual(out['members'][1]['name']['source']['page'],3)
        householder=next(f for f in out['fields'] if f['key']=='householder')
        self.assertFalse(householder['need_review'])

    def test_mrz_corruption_is_not_repaired(self):
        a='P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<'
        b='L898902C36UTO7408122F1204159ZE184226B<<<<<11'
        out=extract_document_fields([evidence(a+'\n'+b)],'PASSPORT')
        mrz=next(f for f in out['fields'] if f['key']=='mrz')
        self.assertEqual(mrz['value'],a+'\n'+b)
        self.assertTrue(any(c['status']=='FAIL' for c in mrz['validation_checks']))
        self.assertTrue(any(not i['can_accept'] for i in mrz['review_issues']))


if __name__=='__main__': unittest.main()
