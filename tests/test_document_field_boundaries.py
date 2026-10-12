"""Adjacent printed labels must not become somebody else's field value."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.extraction import extract_result


def block(text, page=1, bbox=None):
    return dict(text=text, page=page, region_id=f'p{page}',
                bbox=bbox or [0, 0, 1, 1], extraction_method='pdf_text')


def fields(kind, text):
    return {f['key']: f for f in extract_result([block(text)], kind)['fields']}


class DocumentFieldBoundaryTests(unittest.TestCase):
    def test_household_member_demographics_remain_on_their_own_pages(self):
        result = extract_result([
            block('户别：家庭户\n户主姓名：测试甲\n户号：000001\n住址：民族团结路'),
            block('常住人口登记卡\n姓名：测试甲\n性别 男民族汉', 2),
            block('常住人口登记卡\n姓名：测试乙\n性别 女 民族回', 3),
        ], 'HOUSEHOLD_REGISTER')
        for member, sex, ethnicity, page in zip(result['members'], ['M', 'F'], ['汉', '回'], [2, 3]):
            self.assertEqual(member['gender']['value'], sex)
            self.assertEqual(member['ethnicity']['value'], ethnicity)
            self.assertEqual(member['ethnicity']['source']['page'], page)
        self.assertEqual(next(f for f in result['fields'] if f['key'] == 'address')['value'], '民族团结路')

    def test_compact_demographic_neighbor_in_xuexin_and_passport(self):
        for kind, text, key, value in [
            ('XUEXIN_DIPLOMA_TABLE', '教育部学历证书电子注册备案表\n性别 男 出生日期1990年1月2日', 'birth_date', '1990-01-02'),
            ('PASSPORT', '<table><tr><td>性别</td><td>女 国籍CHN</td></tr></table>', 'nationality', 'CHN'),
        ]:
            with self.subTest(kind=kind):
                actual = fields(kind, text)
                self.assertEqual(actual['gender']['value'], 'M' if kind.startswith('XUEXIN') else 'F')
                self.assertEqual(actual[key]['value'], value)
                self.assertIn(actual[key]['source']['raw_text'], actual['gender']['source']['raw_text'])

    def test_compact_demographics_keep_other_labels_and_invalid_dates_out(self):
        actual = fields('ID_CARD_FRONT', '性别 男 民族汉出生日期1990年1月2日')
        self.assertEqual(actual['gender']['value'], 'M')
        self.assertIsNone(actual['ethnicity']['value'])
        actual = fields('PASSPORT', '性别 女 出生日期1990年2月30日')
        self.assertEqual(actual['gender']['value'], 'F')
        self.assertIsNone(actual['birth_date']['value'])

    def test_native_demographic_value_keeps_its_real_source(self):
        result = extract_result([
            block('性 别', bbox=[.1, .1, .3, .15]),
            block('男 民族汉', bbox=[.4, .1, .8, .15]),
        ], 'ID_CARD_FRONT')
        actual = {f['key']: f for f in result['fields']}
        for key, value in [('gender', 'M'), ('ethnicity', '汉')]:
            self.assertEqual(actual[key]['value'], value)
            self.assertEqual(actual[key]['source']['bbox'], [.4, .1, .8, .15])
            self.assertEqual(actual[key]['source']['raw_text'], '性 别：男 民族汉')

    def test_shared_profiles_do_not_put_compact_gender_in_a_holder_name(self):
        for kind, prefix in [('ID_CARD_FRONT', ''), ('PASSPORT', ''),
                             ('XUEXIN_DIPLOMA_TABLE', '教育部学历证书电子注册备案表\n')]:
            with self.subTest(kind=kind):
                actual = fields(kind, prefix + '姓名：测试甲性别男')
                self.assertEqual(actual['name']['value'], '测试甲')
                self.assertEqual(actual['gender']['value'], 'M')
        actual = fields('ID_CARD_FRONT', '姓名：测试甲性别男民族汉')
        self.assertEqual(actual['name']['value'], '测试甲')
        self.assertEqual(actual['gender']['value'], 'M')
        self.assertEqual(actual['ethnicity']['value'], '汉')

    def test_id_validity_is_not_part_of_issuing_authority(self):
        for text in [
            '签发机关：测试公安局 有效期限 2020.01.02-长期',
            '<table><tr><td>签发机关</td><td>测试公安局</td><td>有效期限</td><td>2020.01.02-2030.01.02</td></tr></table>',
        ]:
            with self.subTest(text=text):
                actual = fields('ID_CARD_BACK', text)
                self.assertEqual(actual['issuing_authority']['value'], '测试公安局')
                self.assertEqual(actual['valid_from']['value'], '2020-01-02')
                self.assertEqual(actual['valid_to']['value'], '2030-01-02' if '<table' in text else '长期')
                self.assertEqual(len(actual), 3)

    def test_licence_combined_term_does_not_pollute_its_neighbor(self):
        actual = fields('BUSINESS_LICENSE', '成立日期：2020年1月2日 营业期限 2020年1月2日至长期')
        self.assertEqual(actual['established_date']['value'], '2020-01-02')
        self.assertEqual(actual['business_term_start']['value'], '2020-01-02')
        self.assertEqual(actual['business_term_end']['value'], '长期')

    def test_term_disagreements_are_not_silently_selected(self):
        actual = fields('ID_CARD_BACK', '有效期限：2020.01.02-长期\n有效期限止：2030.01.02')
        self.assertIsNone(actual['valid_to']['value'])
        self.assertEqual({c['value'] for c in actual['valid_to']['candidates']}, {'长期', '2030-01-02'})

    def test_term_labels_embedded_in_ordinary_text_do_not_seed_dates(self):
        actual = fields('BUSINESS_LICENSE', '经营范围：代办营业期限2020年1月2日至长期')
        self.assertEqual(actual['business_scope']['value'], '代办营业期限2020年1月2日至长期')
        self.assertIsNone(actual['business_term_start']['value'])
        self.assertIsNone(actual['business_term_end']['value'])
        actual = fields('ID_CARD_FRONT', '住址：民族团结路')
        self.assertEqual(actual['address']['value'], '民族团结路')
        self.assertIsNone(actual['ethnicity']['value'])

    def test_certificate_name_does_not_include_a_compact_gender_label(self):
        for kind in ['DIPLOMA', 'DEGREE_CERT']:
            for text in ['姓名：测试甲性别女', '姓名：测试甲 性 别女',
                         '<table><tr><td>姓名</td><td>测试甲性别女</td></tr></table>']:
                with self.subTest(kind=kind, text=text):
                    actual = fields(kind, text)
                    self.assertEqual(actual['name']['value'], '测试甲')
                    self.assertEqual(actual['gender']['value'], 'F')
                    self.assertIn('性', actual['gender']['source']['raw_text'])

    def test_normal_adjacent_labels_across_document_families(self):
        for kind, text, expected in [
            ('ID_CARD_FRONT', '姓名：测试甲 性别：男 民族：汉', dict(name='测试甲', gender='M', ethnicity='汉')),
            ('ID_CARD_BACK', '签发机关：测试公安局 有效期限止：长期', dict(issuing_authority='测试公安局', valid_to='长期')),
            ('BANK_CARD', '持卡人姓名：TEST USER 有效期：12/30\n卡号：4111111111111111', dict(holder_name='TEST USER', valid_thru='12/30', card_number='4111111111111111')),
            ('BUSINESS_LICENSE', '名称：测试公司 类型：有限责任公司', dict(company_name='测试公司', company_type='有限责任公司')),
            ('XUEXIN_DIPLOMA_TABLE', '教育部学历证书电子注册备案表\n学历层次：本科 学历类别：普通高等教育 学习形式：普通全日制', dict(education_level='本科', education_category='普通高等教育', study_mode='普通全日制')),
            ('PASSPORT', '姓：TEST 名：USER 性别：F 国籍：CHN', dict(surname='TEST', given_names='USER', gender='F', nationality='CHN')),
            ('HOUSEHOLD_REGISTER', '户主姓名：测试甲 户号：000001 住址：民族团结路', dict(householder='测试甲', household_no='000001', address='民族团结路')),
            ('DIPLOMA', '学校名称：测试大学 专业：计算机科学 学历层次：本科', dict(school_name='测试大学', major='计算机科学', education_level='本科')),
            ('DEGREE_CERT', '学校名称：测试大学 学位级别：学士 学位名称：工学学士', dict(school_name='测试大学', degree_category='学士', degree_name='工学学士')),
        ]:
            with self.subTest(kind=kind):
                actual = fields(kind, text)
                self.assertEqual({key: actual[key]['value'] for key in expected}, expected)

    def test_generic_text_is_not_reinterpreted_as_typed_demographics(self):
        text = '备注：性别 男 民族汉'
        result = extract_result([block(text)], 'GENERIC')
        self.assertEqual(result['generic']['full_text'], text)
        self.assertEqual(result['generic']['key_values'][0]['value'], '性别 男 民族汉')


if __name__ == '__main__':
    unittest.main()
