"""A local Windows user's API identity; no key embedded in the frontend or URL."""
import getpass
import hashlib
import hmac
import os
import secrets
import uuid
from pathlib import Path


class Accounts:
    def __init__(self, storage):
        self.storage = storage
        self.path = storage.root.parent / 'secrets' / 'accounts.enc'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            account = dict(user_id=str(uuid.uuid4()), display_name=getpass.getuser(), role='operator',
                           key=secrets.token_urlsafe(32))
            with self.path.open('xb') as stream:
                stream.write(storage.pack([account]))
                stream.flush()
                os.fsync(stream.fileno())
        self.accounts = storage.unpack(self.path.read_bytes())

    def authenticate(self, key):
        if not isinstance(key, str) or not 20 <= len(key) <= 128:
            return None
        digest = hashlib.sha256(key.encode()).digest()
        for account in self.accounts:
            if hmac.compare_digest(digest, hashlib.sha256(account['key'].encode()).digest()):
                return {k: v for k, v in account.items() if k != 'key'}
        return None

    def current_key(self):
        return self.accounts[0]['key']
