"""Known-value privacy patterns; never infer identities from arbitrary raw prose."""
import re
import unicodedata

SENSITIVE_KEYS = frozenset({'id_number','card_number','passport_number','certificate_no',
                           'online_verification_code','household_no','report_no','phone'})
_LABELS = {
    'id_number': ('公民身份号码','身份证号码','身份证号'),
    'card_number': ('卡号','银行卡号'),
    'passport_number': ('护照号码','护照号','Passport No.','Passport Number'),
    'certificate_no': ('证书编号','证书号码','学位证书编号','毕业证书编号'),
    'online_verification_code': ('在线验证码',),
    'household_no': ('户号',), 'report_no': ('体检编号','报告编号','条码号'),
    'phone': ('手机号码','手机号','联系电话','电话'),
}
_SEPARATOR = r'[\s()（）\-‐‑–—]*'
_BOUNDARY = 'A-Za-z0-9Ａ-Ｚａ-ｚ０-９.*'


def _canonical(key, value):
    if not isinstance(value,str) or '*' in value or len(value)>160:
        return None
    compact=re.sub(_SEPARATOR,'',unicodedata.normalize('NFKC',value))
    if key=='phone':
        match=re.fullmatch(r'(?:\+?86)?(1[3-9][0-9]{9})',compact)
        return match[1] if match else None
    patterns={
        'id_number': r'(?:[0-9]{15}|[0-9]{17}[0-9Xx])',
        'card_number': r'[0-9]{13,19}',
        # Format coverage for masking is broader than document validity rules.
        'passport_number': r'(?=[A-Za-z0-9]{6,12}$)(?=.*[0-9])[A-Za-z0-9]+',
        'online_verification_code': r'(?:[A-Za-z0-9]{12}|[A-Za-z0-9]{16})',
        'certificate_no': r'(?=[A-Za-z0-9]{6,40}$)(?=.*[0-9])[A-Za-z0-9]+',
        'household_no': r'(?=[A-Za-z0-9]{4,32}$)(?=.*[0-9])[A-Za-z0-9]+',
        'report_no': r'(?=[A-Za-z0-9]{4,40}$)(?=.*[0-9])[A-Za-z0-9]+',
    }
    if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?[Ee][+-]?[0-9]+',value.strip()):
        return None
    return compact if re.fullmatch(patterns[key],compact) else None


def _typed_fields(result):
    fields=result.get('fields',[])
    if isinstance(fields,list):
        yield from (f for f in fields if isinstance(f,dict))
    info=result.get('basic_info',{})
    if isinstance(info,dict):
        for key,field in info.items():
            if isinstance(field,dict):yield dict(field,key=key)
    for member in result.get('members',[]):
        if not isinstance(member,dict):continue
        if isinstance(member.get('fields'),list):
            yield from (f for f in member['fields'] if isinstance(f,dict))
        else:
            for key,field in member.items():
                if isinstance(field,dict):yield dict(field,key=key)


def _raw_candidate(field, key):
    """Recover a full typed source value even when its display was already masked."""
    source=field.get('source')
    if not isinstance(source,dict) or not isinstance(source.get('raw_text'),str):return None
    raw=source['raw_text'].strip()
    if _canonical(key,raw):return raw
    labels=(*_LABELS.get(key,()),field.get('label',''))
    for label in labels:
        if not label:continue
        match=re.fullmatch(re.escape(label)+r'\s*[:：]\s*(.+)',raw,re.S)
        if match and _canonical(key,match[1]):return match[1]
    return None


def _character(character):
    choices={character}
    if character.isascii() and character.isalnum():
        choices.add(chr(ord(character)+0xFEE0))
        if character.isalpha():
            choices.update((character.swapcase(),chr(ord(character.swapcase())+0xFEE0)))
    return '['+''.join(re.escape(c) for c in sorted(choices))+']'


def sensitive_patterns(result):
    """Return (compiled regex, replacement) pairs for existing recursive masked().

    Values and all candidates in typed fields authorize matching. Matching is
    bounded and permits only display separators/fullwidth equivalents. Caller
    must retain its UUID/hash metadata exemptions during recursive traversal.
    USCC is deliberately absent: a public business identifier is not a person ID.
    """
    values=set()
    for field in _typed_fields(result):
        key=field.get('key')
        if key not in SENSITIVE_KEYS:continue
        candidates=field.get('candidates') or []
        raw=_raw_candidate(field,key)
        history=field.get('_sensitive_history') or []
        if not isinstance(history,list):history=[]
        for value in [field.get('value'),raw,*history,*(c.get('value') for c in candidates if isinstance(c,dict))]:
            compact=_canonical(key,value)
            if compact:values.add((key,compact))
    # Xuexin metadata may be present in older results lacking a typed field copy.
    info=result.get('xuexin_info')
    if isinstance(info,dict):
        for key in ('online_verification_code','online_verification_code_normalized'):
            compact=_canonical('online_verification_code',info.get(key))
            if compact:values.add(('online_verification_code',compact))
    patterns=[]
    for key,value in sorted(values,key=lambda item:(-len(item[1]),item)):
        body=_SEPARATOR.join(_character(c) for c in value)
        if key=='phone':
            body=r'[（(]?(?:[+＋]?[8８][6６]'+_SEPARATOR+r')?'+body+r'[）)]?'
        pattern=re.compile(r'(?<!['+_BOUNDARY+'])'+body+r'(?!['+_BOUNDARY+'])')
        replacement='****'+value[-4:] if len(value)>4 else '****'
        patterns.append((pattern,replacement))
    return patterns
