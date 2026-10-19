"""Offline script conversion for newly recognized non-name bank fields only."""
from functools import lru_cache


BANK_TEXT_FIELDS = frozenset({'bank_name', 'branch_name', 'card_scheme', 'card_type', 'valid_thru'})


@lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC
    return OpenCC('t2s.json')


def simplify_bank_text(value):
    """Match bank context on a copy; callers retain original evidence and names."""
    return value if value.isascii() else _converter().convert(value)


def normalize_bank_value(key, value):
    return simplify_bank_text(value) if key in BANK_TEXT_FIELDS and value is not None else value
