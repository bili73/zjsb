"""Explicit local credential display. Never called by the HTTP service or logger."""
from ocr_app.config import ROOT
from ocr_app.storage import Storage
from ocr_app.auth import Accounts

if __name__ == '__main__':
    account = Accounts(Storage(ROOT / '.runtime/data'))
    print('Access key for the current Windows account (keep private):')
    print(account.current_key())
