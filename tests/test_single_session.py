"""Thirty-day opaque sessions and atomic last-login-wins, isolated accounts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
import test_business_api as base
from ocr_app.auth import Accounts, SESSION_SECONDS, csrf_for
from ocr_app.db import open_database
from ocr_app.task_store import TaskError


class SingleSessionTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    password = 'synthetic password for login'

    def provision(self):
        return self.business.accounts.set_user('tester', self.password, '合成用户', 'operator')

    def test_thirty_day_cookie_matches_absolute_server_expiry_and_does_not_slide(self):
        self.provision()
        self.assertEqual(SESSION_SECONDS, 2592000)
        with patch('ocr_app.auth.time', return_value=2_000_000_000):
            response = self.client.post('/api/v1/auth/login', headers={'Origin': 'http://127.0.0.1'},
                                         json=dict(username='tester', password=self.password))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Max-Age=2592000', response.headers['set-cookie'])
        token = self.client.cookies.get('ocr_session')
        with self.business.engine.connect() as c:
            expiry = c.execute(text('SELECT expires_at FROM web_sessions')).scalar_one()
        self.assertEqual(expiry, 2_000_000_000 + SESSION_SECONDS)
        with patch('ocr_app.auth.time', return_value=expiry - 1):
            self.assertIsNotNone(Accounts(self.business.storage, self.business.engine).session(token))
            self.assertEqual(self.client.get('/api/v1/auth/me').status_code, 200)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT expires_at FROM web_sessions')).scalar_one(), expiry)
        with patch('ocr_app.auth.time', return_value=expiry):
            self.assertIsNone(self.business.accounts.session(token))
            self.assertEqual(self.client.get('/api/v1/auth/me').status_code, 401)

    def test_new_login_displaces_old_only_on_success_and_old_logout_keeps_replacement(self):
        self.provision()
        accounts = self.business.accounts
        first = accounts.login('tester', self.password, 'first device')
        with self.assertRaises(TaskError): accounts.login('tester', 'wrong password', 'second device')
        self.assertIsNotNone(accounts.session(first))
        second = accounts.login('tester', self.password, 'second device')
        self.assertIsNone(accounts.session(first))
        self.assertIsNotNone(accounts.session(second))
        accounts.logout(first)
        self.assertIsNotNone(accounts.session(second))
        old = dict(Cookie='ocr_session=' + first, Origin='http://127.0.0.1', **{'X-CSRF-Token': csrf_for(first)})
        new = dict(old, Cookie='ocr_session=' + second, **{'X-CSRF-Token': csrf_for(second)})
        self.assertEqual(self.client.get('/api/v1/batches', headers=old).status_code, 401)
        self.assertEqual(self.client.post('/api/v1/export', headers=old, json={}).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=new).status_code, 200)

    def test_simultaneous_logins_leave_one_valid_token_and_other_accounts_are_independent(self):
        user = self.provision()
        self.business.accounts.set_user('other', self.password, '其他用户', 'operator')
        other = self.business.accounts.login('other', self.password, 'other device')
        with ThreadPoolExecutor(2) as pool:
            tokens = list(pool.map(lambda i: self.business.accounts.login('tester', self.password, str(i)), range(2)))
        valid = [t for t in tokens if self.business.accounts.session(t)]
        self.assertEqual(len(valid), 1)
        self.assertIsNotNone(self.business.accounts.session(other))
        with self.business.engine.connect() as c:
            rows = c.execute(text('SELECT token_hash FROM web_sessions WHERE user_id=:id'), {'id': user['user_id']}).all()
        self.assertEqual(rows, [(hashlib.sha256(valid[0].encode()).hexdigest(),)])


class SingleSessionMigrationTests(unittest.TestCase):
    def test_deduplication_is_deterministic_preserves_latest_expiry_and_enforces_uniqueness(self):
        from alembic import command
        from alembic.config import Config
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'tasks.sqlite3'))
            config = Config()
            config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'backend/migrations'))
            with engine.begin() as c:
                config.attributes['connection'] = c
                command.upgrade(config, '0007')
                for user in ['alice', 'bob']:
                    c.execute(text('INSERT INTO web_users VALUES (:id,:id,:id,\'operator\',\'original hash\',1)'), {'id': user})
                for token, user, expiry in [('old', 'alice', 10), ('new-a', 'alice', 20), ('new-b', 'alice', 20), ('bob-token', 'bob', 15)]:
                    c.execute(text('INSERT INTO web_sessions VALUES (:token,:user,:expires)'), dict(token=token, user=user, expires=expiry))
                original = c.execute(text('SELECT * FROM web_users ORDER BY id')).all()
            engine.dispose()
            for _ in range(2):
                engine = open_database(root)
                with engine.connect() as c:
                    self.assertEqual(c.execute(text('SELECT * FROM web_users ORDER BY id')).all(), original)
                    self.assertEqual(c.execute(text('SELECT * FROM web_sessions ORDER BY user_id')).all(), [('new-b', 'alice', 20), ('bob-token', 'bob', 15)])
                engine.dispose()
            engine = open_database(root)
            with self.assertRaises(IntegrityError), engine.begin() as c:
                c.execute(text("INSERT INTO web_sessions VALUES ('forbidden duplicate','alice',100)"))
            engine.dispose()
