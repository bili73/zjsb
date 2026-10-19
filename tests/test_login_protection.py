"""Persistent login budgets and prompt password-work rejection; no real accounts."""
import concurrent.futures
import hashlib
import threading
import unittest
from unittest.mock import patch
from time import monotonic

from sqlalchemy import text

import test_business_api as base
from ocr_app.auth import Accounts
from ocr_app.task_errors import TaskError


class LoginProtectionTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    password = 'synthetic login password'

    def provision(self):
        self.accounts = self.business.accounts
        self.accounts.set_user('tester', self.password, '合成测试账号')

    def denied(self, username='tester', peer='peer', password='wrong synthetic password'):
        try:
            self.accounts.login(username, password, peer)
        except TaskError as error:
            return error
        self.fail('Expected login rejection')

    def test_account_limit_spans_peers_case_and_restart_with_retry_header(self):
        self.provision()
        with patch('ocr_app.auth.time', return_value=1000):
            for i in range(5):
                self.assertEqual(self.denied('TeStEr', str(i)).status, 401)
            self.accounts = Accounts(self.business.storage, self.business.engine)
        with patch('ocr_app.auth.time', return_value=1010):
            error = self.denied(peer='fresh peer', password=self.password)
            self.assertEqual((error.code, error.retry_after), ('LOGIN_THROTTLED', 290))
        with patch('ocr_app.auth.time', return_value=1300):
            self.assertTrue(self.accounts.login('tester', self.password, 'fresh peer'))

    def test_source_aggregate_does_not_reset_on_success_and_other_accounts_are_independent(self):
        self.provision()
        for i in range(59):
            self.assertEqual(self.denied(username='missing-' + str(i)).status, 401)
        self.assertTrue(self.accounts.login('tester', self.password, 'peer'))
        self.assertEqual(self.denied(username='fresh-name').status, 429)
        self.assertTrue(self.accounts.login('tester', self.password, 'other-peer'))

    def test_success_resets_only_current_account_window(self):
        self.provision()
        for _ in range(4):
            self.assertEqual(self.denied().status, 401)
        self.accounts.login('tester', self.password, 'peer')
        for _ in range(5):
            self.assertEqual(self.denied().status, 401)
        self.assertEqual(self.denied().status, 429)

    def test_exactly_two_verifications_and_slots_released_on_exception(self):
        self.provision()
        self.accounts.dummy_hash = self.accounts.hasher.hash(self.password)
        started = threading.Barrier(3)
        release = threading.Event()
        original = self.accounts.hasher.verify
        def verify(encoded, password):
            started.wait(timeout=8)
            self.assertTrue(release.wait(timeout=8))
            return original(encoded, password)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            with patch.object(type(self.accounts.hasher), 'verify', side_effect=verify):
                futures = [pool.submit(self.denied, username='synthetic-' + str(i)) for i in range(2)]
                try:
                    started.wait(timeout=8)
                    error = self.denied(username='third')
                    self.assertEqual((error.status, error.retry_after), (429, 1))
                finally:
                    release.set()
                self.assertEqual([f.result().status for f in futures], [401, 401])
        with patch.object(type(self.accounts.hasher), 'verify', side_effect=RuntimeError('synthetic hasher failure')):
            with self.assertRaises(RuntimeError):
                self.accounts.login('tester', self.password, 'peer')
        self.assertTrue(self.accounts.login('tester', self.password, 'peer'))

    def test_http_throttle_has_bounded_audit_writes_and_forwarded_headers_do_not_bypass(self):
        self.provision()
        for i in range(16):
            response = self.client.post('/api/v1/auth/login', headers={
                'Origin': 'http://127.0.0.1', 'X-Forwarded-For': f'203.0.113.{i}'},
                json={'username': 'tester', 'password': 'wrong synthetic password'})
            self.assertEqual(response.status_code, 401 if i < 5 else 429, response.text)
            if i >= 5:
                self.assertTrue(1 <= int(response.headers['Retry-After']) <= 300)
        with self.business.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM audit WHERE event='login' AND outcome='failure'")).all()
        self.assertEqual(len(rows), 6)

    def test_inflight_success_cannot_clear_a_newer_account_window(self):
        self.provision()
        original = self.accounts.hasher.verify
        def advance(encoded, password):
            with patch('ocr_app.auth.time', return_value=1301):
                self.accounts._attempt('tester', 'new peer')
            return original(encoded, password)
        with patch('ocr_app.auth.time', return_value=1000), patch.object(type(self.accounts.hasher), 'verify', side_effect=advance):
            self.assertTrue(self.accounts.login('tester', self.password, 'original peer'))
        key = hashlib.sha256(b'account\0tester').hexdigest()
        with self.business.engine.connect() as c:
            row = c.execute(text('SELECT * FROM login_attempts WHERE client_hash=:key'), {'key': key}).mappings().one()
            self.assertEqual((row['window_start'], row['attempts']), (1301, 1))

    def test_legacy_peer_limit_is_not_reset_by_upgrade_and_expires(self):
        self.provision()
        with self.business.store.transaction() as c:
            c.execute(text('INSERT INTO login_attempts VALUES (:key,1000,5)'),
                      {'key': hashlib.sha256(b'peer').hexdigest()})
        with patch('ocr_app.auth.time', return_value=1001):
            self.assertEqual(self.denied(password=self.password).retry_after, 299)
        with patch('ocr_app.auth.time', return_value=1300):
            self.assertTrue(self.accounts.login('tester', self.password, 'peer'))

    def test_parallel_reservations_cannot_exceed_account_allowance(self):
        self.provision()
        barrier = threading.Barrier(12)
        def reserve(index):
            barrier.wait(timeout=8)
            try:
                self.accounts._attempt('tester', 'source-' + str(index))
                return 200
            except TaskError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(12) as pool:
            outcomes = list(pool.map(reserve, range(12)))
        self.assertEqual((outcomes.count(200), outcomes.count(429)), (5, 7))

    def test_http_reads_continue_while_two_password_checks_are_running(self):
        self.provision()
        token = self.accounts.login('tester', self.password, 'existing-session')
        started, release = threading.Barrier(3), threading.Event()
        original = self.accounts.hasher.verify
        def verify(encoded, password):
            started.wait(timeout=8)
            if not release.wait(timeout=8):
                raise RuntimeError('Synthetic verification barrier timed out')
            return original(encoded, password)
        def submit():
            return self.client.post('/api/v1/auth/login', headers={'Origin': 'http://127.0.0.1'},
                                    json={'username': 'tester', 'password': 'wrong synthetic password'})
        with concurrent.futures.ThreadPoolExecutor(2) as pool, patch.object(type(self.accounts.hasher), 'verify', side_effect=verify):
            futures = [pool.submit(submit) for _ in range(2)]
            try:
                started.wait(timeout=8)
                at = monotonic()
                response = submit()
                self.assertEqual((response.status_code, response.headers.get('Retry-After')), (429, '1'))
                response = self.client.get('/api/v1/batches', headers={'Cookie': 'ocr_session=' + token})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertLess(monotonic() - at, 2, 'Login work must not hold the page read path')
            finally:
                release.set()
            self.assertEqual([f.result().status_code for f in futures], [401, 401])


if __name__ == '__main__':
    unittest.main()
