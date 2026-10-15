"""Canonical field metadata shared by extraction and human review."""
from copy import deepcopy


def _fields(spec):
    result = []
    for token in spec.split('|'):
        key, label, *flags = token.split(':')
        result.append(dict(key=key, label=label, required='required' in flags,
                           editable='derived' not in flags,
                           type=next((f for f in flags if f in {'date', 'enum', 'integer'}), 'string')))
    return result


PROFILES = {
    'ID_CARD_FRONT': _fields('name:姓名:required|gender:性别:required:enum|ethnicity:民族:required|birth_date:出生日期:required:date|address:住址:required|id_number:公民身份号码:required'),
    'ID_CARD_BACK': _fields('issuing_authority:签发机关:required|valid_from:有效期限起:date|valid_to:有效期限止:required:date'),
    'DIPLOMA': _fields('name:姓名:required|gender:性别:enum|birth_date:出生日期:date|school_name:学校名称:required|major:专业:required|education_level:学历层次:required:enum|duration:学制|enroll_date:入学日期:date|graduate_date:毕业日期:required:date|certificate_no:证书编号:required|issue_date:发证日期:date'),
    'DEGREE_CERT': _fields('name:姓名:required|gender:性别:enum|birth_date:出生日期:date|school_name:学校名称:required|major:专业:required|degree_category:学位级别:required:enum|degree_name:学位名称|study_mode:学习形式:enum|certificate_no:学位证书编号:required|award_date:学位授予日期:required:date'),
    'MEDICAL_REPORT': _fields('name:姓名:required|gender:性别:required:enum|age:年龄:integer|exam_date:体检日期:required:date|institution:体检机构|report_date:报告日期:date|height:身高|weight:体重|blood_pressure:血压|blood_routine:血常规|urine_routine:尿常规|ecg:心电图|dr_imaging:DR影像|abdominal_ultrasound:腹部彩超|liver_function:肝功五项（生化检测）|exam_project_count:体检项目数量:integer:derived|exam_projects:体检项目'),
    'BANK_CARD': _fields('holder_name:姓名|card_number:卡号:required|bank_name:开户行|branch_name:开户支行|bin_code:发卡行识别码:derived|card_scheme:卡组织:enum|card_type:卡种:enum|valid_thru:有效期'),
    'BUSINESS_LICENSE': _fields('unified_social_credit_code:统一社会信用代码:required|company_name:名称:required|company_type:类型:required:enum|legal_representative:法定代表人:required|registered_capital:注册资本:required|established_date:成立日期:required:date|business_term_start:营业期限起:date|business_term_end:营业期限止:date|business_scope:经营范围:required|registered_address:住所:required|registration_authority:登记机关:required|issue_date:核准日期:date|registration_no:注册号|license_version:版式:enum'),
    'XUEXIN_DIPLOMA_TABLE': _fields('name:姓名:required|gender:性别:required:enum|birth_date:出生日期:required:date|enroll_date:入学日期:date|graduate_date:毕（结）业日期:required:date|school_name:学校名称:required|school_location:院校所在地|major:专业名称:required|education_level:学历层次:required:enum|education_category:学历类别:enum|study_mode:学习形式:enum|duration:学制|graduate_conclusion:毕（结）业结论:enum|certificate_no:证书编号:required|principal:校（院）长姓名|online_verification_code:在线验证码:required|report_update_date:更新日期:date|valid_until:验证有效期至:date|report_language:报告语种:required:enum'),
    'PASSPORT': _fields('passport_number:护照号码:required|name:姓名:required|surname:姓|given_names:名|gender:性别:enum|nationality:国籍:required|birth_date:出生日期:required:date|birth_place:出生地点|issue_date:签发日期:date|expiry_date:有效期至:required:date|issuing_authority:签发机关|issuing_country:签发国|document_code:证件代码|mrz:机读区'),
    'HOUSEHOLD_REGISTER': _fields('household_type:户别:required|householder:户主姓名:required|household_no:户号:required|address:住址:required|issued_by:签发机关|issued_date:签发日期:date|registrar:承办人'),
    'GENERIC': [],
    'TABLE': [],
}
MEMBER_PROFILE = _fields('name:姓名:required|gender:性别:enum|birth_date:出生日期:date|ethnicity:民族|birth_place:出生地|native_place:籍贯|id_number:公民身份号码|relation_to_householder:与户主关系|education:文化程度|marital_status:婚姻状况|occupation:职业|workplace:服务处所|migration_address:迁入地址')
LABELS = dict(zip(PROFILES, ['身份证人像面','身份证国徽面','毕业证','学位证','体检报告','银行卡','营业执照','学历证书电子注册备案表','护照','户口本','通用识别']))
LABELS['TABLE'] = '表格'
PROFILES['INTERVIEW_FORM'] = _fields('name:姓名:required|gender:性别:required:enum|age:年龄:required:integer|id_number:身份证号:required|mobile_number:手机号:required')
LABELS['INTERVIEW_FORM'] = '面试登记表'
SUPPORTED = frozenset(PROFILES)


def profile(doc_type, values=None, required_overrides=None):
    if doc_type not in PROFILES:
        raise ValueError('UNSUPPORTED_DOC_TYPE')
    result = deepcopy(PROFILES[doc_type])
    values = values or {}
    for field in result:
        if doc_type == 'BUSINESS_LICENSE' and field['key'] == 'unified_social_credit_code':
            field['required_when'] = 'no explicitly printed legacy registration_no without USCC'
            if values.get('registration_no') and not values.get('unified_social_credit_code'):
                field['required'] = False
        if doc_type == 'BUSINESS_LICENSE' and field['key'] == 'registration_no':
            field['required_when'] = 'legacy registration_no is printed and USCC is absent'
            if values.get('registration_no') and not values.get('unified_social_credit_code'):
                field['required'] = True
        if doc_type == 'BUSINESS_LICENSE' and field['key'] == 'registered_capital':
            field['required_when'] = 'company_type is not explicitly an individual business, sole proprietorship or partnership'
            if values.get('company_type') in {'个体工商户','个人独资企业','合伙企业'}:
                field['required'] = False
        if doc_type == 'HOUSEHOLD_REGISTER' and field['key'] == 'householder':
            field['required_when'] = 'household_type is not explicitly collective'
            if '集体' in str(values.get('household_type') or ''):
                field['required'] = False
    if required_overrides is not None and doc_type in required_overrides:
        selected = set(required_overrides[doc_type])
        for field in result:
            field['required'] = field['key'] in selected
            field.pop('required_when', None)
    return result


def member_profile(required_overrides=None):
    result = deepcopy(MEMBER_PROFILE)
    if required_overrides is not None and 'HOUSEHOLD_REGISTER' in required_overrides:
        selected = set(required_overrides['HOUSEHOLD_REGISTER'])
        for field in result:
            field['required'] = 'members.' + field['key'] in selected
    return result


def generic_required(required_overrides=None):
    return required_overrides is None or 'GENERIC' not in required_overrides or 'generic.full_text' in required_overrides['GENERIC']


def catalogue(required_overrides=None):
    return [dict(doc_type=kind, label=LABELS[kind], fields=profile(kind, required_overrides=required_overrides)) for kind in PROFILES]
