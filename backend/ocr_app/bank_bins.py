"""Pinned offline community BIN lookup; no network or account verification."""
import csv
from functools import lru_cache
import hashlib
import io
from pathlib import Path
import re
import unicodedata

DATA=Path(__file__).with_name('data')/'bank_bins'
REVISION='de631827ffe8db2792d140f3476b02498fc1244f'
HASHES={'bin.csv':'9ebabf828af89e50c6fbfdcaac3cf6f46757d36003007a9458b5c04fc1140de6',
        'name.csv':'1a77cec8dacac144179173917512500b63a7814005ad15d04cd722d11558b20f'}
SOURCE_URL='https://github.com/hexindai/bcbc/tree/'+REVISION


def normalize_pan(value):
    return re.sub(r'[\s-]','',unicodedata.normalize('NFKC',value)) if isinstance(value,str) else ''


@lru_cache(maxsize=1)
def _data():
    loaded={}
    for name,expected in HASHES.items():
        raw=(DATA/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('BIN_DATA_HASH_MISMATCH')
        loaded[name]=list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
    return loaded['bin.csv'],{r['bank']:r['name'] for r in loaded['name.csv'] if r.get('bank')}


def lookup_bank(number):
    """Select specificity first, then length; unsupported longer rules veto."""
    result=dict(status='UNKNOWN',reason_code='NO_MATCH',prefix=None,bank_code=None,bank_name=None,card_type=None)
    number=normalize_pan(number)
    if not re.fullmatch(r'[0-9]{10,19}',number):
        return dict(result,reason_code='INVALID_PAN')
    try:rows,names=_data()
    except (OSError,ValueError,KeyError):return dict(result,reason_code='DATA_UNAVAILABLE')
    matching=[row for row in rows if number.startswith(row['bin'])]
    if not matching:return result
    length=max(len(row['bin']) for row in matching)
    if length not in {6,8}:return dict(result,reason_code='UNSUPPORTED_PREFIX_LENGTH')
    winners=[row for row in matching if len(row['bin'])==length]
    winners=[row for row in winners if str(len(number))==row['length']]
    if not winners:return dict(result,reason_code='PAN_LENGTH_MISMATCH')
    values={(row['bin'],row['bank'],row['type']) for row in winners}
    if len(values)!=1:return dict(result,status='CONFLICT',reason_code='AMBIGUOUS_RULE')
    prefix,bank,kind=next(iter(values))
    if not names.get(bank) or kind not in {'DC','CC','SCC','PC'}:
        return dict(result,reason_code='INCOMPLETE_RULE')
    return dict(status='MATCHED',reason_code='MATCHED',prefix=prefix,bank_code=bank,bank_name=names[bank],card_type=kind,pan_length=len(number))


def derivation(match):
    return dict(method='offline_bin',input_field='card_number',dataset_id='hexindai-bcbc',
                dataset_version=REVISION,data_updated_at='2020-12-11',retrieved_at='2026-10-08',
                source_url=SOURCE_URL,license='MIT',data_sha256=HASHES['bin.csv'],
                names_sha256=HASHES['name.csv'],matched_prefix=match['prefix'],bank_code=match['bank_code'],card_number_length=match['pan_length'])
