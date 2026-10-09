"""Pure, versioned local checks. PASS never establishes official authenticity."""
import re
import unicodedata
from datetime import date

RULE_SOURCES = {
    'id_cn_v1': 'https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=080D6FBF2BB468F9007657F26D60013E',
    'uscc_v1': 'https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=24691C25985C1073D3A7C85629378AC0',
    'td3_v1': 'https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf',
    'iin_v1': 'https://www.iso.org/news/2016/11/Ref2146.html',
    'luhn_v1': 'https://www.wearepay.uk/what-we-do/standards-authority/obtaining-a-standard-or-identifier-number/iin/',
    'xuexin_compat_v1': 'https://www.chsi.com.cn/xlcx/bgcx.jsp',
}
USCC_CHARS = '0123456789ABCDEFGHJKLMNPQRTUWXY'


def check(kind, status, rule_id, message):
    return dict(kind=kind, status=status, rule_id=rule_id, message=message)


def _calendar(value):
    try:
        parts = [int(x) for x in value.split('-')]
        if len(parts) not in (2, 3): return False
        date(*parts, *([1] if len(parts) == 2 else []))
        return bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?', value))
    except (ValueError, TypeError): return False


def mrz_digit(value):
    numbers = [0 if c == '<' else int(c) if c.isdigit() else ord(c)-55 for c in value]
    return str(sum(n * (7,3,1)[i % 3] for i,n in enumerate(numbers)) % 10)


def validate_field(doc_type, key, value, fields=None):
    if value is None or value == '':
        return [check('FORMAT','UNKNOWN','missing_v1','未提供可校验值。')]
    fields = fields or {}
    if isinstance(fields, list): fields = {f['key']:f.get('value') for f in fields}
    text = str(value).strip()
    out = []
    def add(kind, status, rule, message): out.append(check(kind,status,rule,message))
    if key in {'id_number','unified_social_credit_code'}:
        if key == 'id_number':
            valid = bool(re.fullmatch(r'[0-9]{17}[0-9Xx]',text))
            add('FORMAT','PASS' if valid else 'UNKNOWN','id_cn_v1','18位公民身份号码格式；历史或其他编号需复核。')
            if valid:
                expected='10X98765432'[sum(int(c)*w for c,w in zip(text[:17],[7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2])) % 11]
                add('CHECKSUM','PASS' if text[-1].upper()==expected else 'FAIL','id_cn_v1','仅校验号码校验位。')
                dob=f'{text[6:10]}-{text[10:12]}-{text[12:14]}'
                add('FORMAT','PASS' if _calendar(dob) else 'FAIL','id_birth_v1','号码中的出生日期合法性。')
                for sibling, derived in [('birth_date',dob),('gender','M' if int(text[16])%2 else 'F')]:
                    if fields.get(sibling) is not None:
                        add('CROSS_DOCUMENT','PASS' if fields[sibling]==derived else 'FAIL','within_document_id_'+sibling+'_v1','号码与本材料明示字段是否一致。')
        else:
            valid=len(text)==18 and all(c in USCC_CHARS for c in text)
            add('FORMAT','PASS' if valid else 'FAIL','uscc_v1','统一社会信用代码字符与长度。')
            if valid:
                expected=USCC_CHARS[(-sum(USCC_CHARS.index(c)*w for c,w in zip(text[:17],[1,3,9,27,19,26,16,17,20,29,25,13,8,24,10,30,28])))%31]
                add('CHECKSUM','PASS' if text[-1]==expected else 'FAIL','uscc_v1','仅校验代码校验位。')
        add('OFFICIAL','UNKNOWN','official_not_requested_v1','未进行官方联网核验。')
    elif key == 'card_number':
        compact=re.sub(r'[\s-]','',unicodedata.normalize('NFKC',text))
        valid=bool(re.fullmatch(r'[0-9]{10,19}',compact))
        add('FORMAT','PASS' if valid else 'FAIL','pan_compat_v1','本地PAN长度兼容检查，不代表已确认发卡产品规则。')
        from .bank_bins import lookup_bank
        matched=lookup_bank(compact)
        add('FORMAT','PASS' if matched['status']=='MATCHED' else 'UNKNOWN','bin_snapshot_v1',
            '仅离线社区表匹配，不代表官方发卡或账户核验。' if matched['status']=='MATCHED' else '离线BIN未能唯一匹配（'+matched['reason_code']+'），不猜测银行。')
        if valid:
            digits=[int(c) for c in compact[::-1]]
            total=sum(n if i%2==0 else (n*2-9 if n>=5 else n*2) for i,n in enumerate(digits))
            arithmetic='通过' if total%10==0 else '未通过'
            add('CHECKSUM','UNKNOWN','luhn_candidate_v1',f'Luhn算术{arithmetic}；缺少已确认的卡产品适用规则，不据此判定号码有效或自动改号。')
        add('OFFICIAL','UNKNOWN','official_not_requested_v1','未进行银行账户要素核验。')
    elif doc_type=='BANK_CARD' and key in {'bank_name','card_type'}:
        from .bank_bins import lookup_bank
        matched=lookup_bank(fields.get('card_number'))
        same=matched['status']=='MATCHED' and text==matched[key]
        add('FORMAT','PASS' if same else 'UNKNOWN','bin_reference_'+key+'_v1',
            '与离线社区表一致，仍非官方核验。' if same else '当前值与离线社区表不一致或表未覆盖；保留原值，请对照原件确认，旧表不能否定人工记录。')
    elif key == 'online_verification_code':
        valid=bool(re.fullmatch(r'(?:[A-Za-z0-9]{12}|[A-Za-z0-9]{16})',re.sub(r'\s','',text)))
        add('FORMAT','PASS' if valid else 'UNKNOWN','xuexin_compat_v1','12/16位ASCII字母数字为本地兼容规则，非完整官方编码规范。')
        add('OFFICIAL','UNKNOWN','official_not_requested_v1','尚未由操作员在学信网核验。')
    elif key == 'mrz':
        lines=text.splitlines()
        valid=len(lines)==2 and all(re.fullmatch('[A-Z0-9<]{44}',line) for line in lines) and lines[0].startswith('P')
        add('FORMAT','PASS' if valid else 'UNKNOWN','td3_v1','仅支持两行各44字符的TD3护照机读区。')
        if valid:
            s=lines[1]
            pairs=[(s[:9],s[9]),(s[13:19],s[19]),(s[21:27],s[27]),(s[28:42],s[42]),(s[:10]+s[13:20]+s[21:43],s[43])]
            passed=all(mrz_digit(part)==digit or (part=='<'*14 and digit=='<') for part,digit in pairs)
            add('CHECKSUM','PASS' if passed else 'FAIL','td3_v1','TD3分项与组合校验位，不进行字符修复。')
        add('OFFICIAL','UNKNOWN','official_not_requested_v1','未核验签发机关或芯片签名。')
    elif key.endswith('_date') or key in {'valid_from','valid_to','valid_until','business_term_start','business_term_end'}:
        long_term=text=='长期' and key in {'valid_to','business_term_end'}
        add('FORMAT','PASS' if long_term or _calendar(text) else 'FAIL','calendar_v1','公历日期检查，不补造缺失日期。')
        start_key={'valid_to':'valid_from','graduate_date':'enroll_date','expiry_date':'issue_date','business_term_end':'business_term_start'}.get(key)
        start=fields.get(start_key) if start_key else None
        if start and _calendar(str(start)) and _calendar(text):
            add('CROSS_DOCUMENT','PASS' if str(start)<=text else 'FAIL','within_document_date_order_v1','本材料结束日期不得早于开始日期。')
    elif key=='valid_thru':
        add('FORMAT','PASS' if re.fullmatch(r'(?:0[1-9]|1[0-2])/[0-9]{2}',text) else 'FAIL','card_expiry_v1','卡面有效期MM/YY格式检查。')
    elif key=='gender':
        add('FORMAT','PASS' if text in ({'M','F','X'} if doc_type=='PASSPORT' else {'M','F'}) else 'UNKNOWN','gender_enum_v1','仅转换明确的性别标记，未知原文需核对。')
    elif key in {'degree_category','education_level','report_language'}:
        allowed = {'degree_category': {'学士','硕士','博士'},
                   'education_level': {'专科','本科','硕士研究生','博士研究生','其他'} if doc_type=='XUEXIN_DIPLOMA_TABLE' else {'专科','本科','研究生','其他'},
                   'report_language': {'zh','en'}}[key]
        add('FORMAT','PASS' if text in allowed else 'UNKNOWN',key+'_enum_v1','未覆盖的原文枚举需人工核对，不能猜测具体层次。')
    return out
