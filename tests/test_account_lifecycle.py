"""Account lifecycle tests use temporary databases and synthetic credentials."""
import concurrent.futures
import threading
import unittest
import uuid
from unittest.mock import patch
from sqlalchemy import event, text
import test_business_api as base
from ocr_app.task_store import TaskError


class AccountLifecycleTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    origin = {'Origin': 'http://127.0.0.1'}
    password = 'synthetic password 2026'
    new_password = 'synthetic replacement 2026'

    def account(self, name='reader', role='operator'):
        return self.business.accounts.set_user(name, self.password, '合成用户', role)

    def login(self, name):
        response = self.client.post('/api/v1/auth/login', headers=self.origin,
                                    json=dict(username=name, password=self.password))
        self.assertEqual(response.status_code, 200, response.text)
        return dict(self.origin, **{'X-CSRF-Token': response.json()['csrf_token']})

    def admin(self):
        user = self.account('admin', 'admin')
        headers = self.login('admin')
        return user, headers, self.client.cookies.get('ocr_session')

    def row(self, user):
        with self.business.engine.connect() as c:
            row = c.execute(text('SELECT * FROM web_users WHERE id=:id'), {'id': user['user_id']}).mappings().first()
            return dict(row) if row else None

    def test_disable_enable_revokes_every_session_without_restoring_them(self):
        _, headers, _ = self.admin()
        user = self.account()
        tokens = [self.business.accounts.login('reader', self.password, 'synthetic') for _ in range(2)]
        path = '/api/v1/admin/users/' + user['user_id']
        before = self.row(user)
        response = self.client.patch(path, headers=headers, json={'enabled': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['enabled'])
        self.assertTrue(all(self.business.accounts.session(token) is None for token in tokens))
        with self.assertRaises(TaskError):
            self.business.accounts.login('reader', self.password, 'synthetic')
        self.assertEqual(self.client.patch(path, headers=headers, json={'enabled': True}).status_code, 200)
        self.assertEqual(self.row(user), before)
        self.assertTrue(all(self.business.accounts.session(token) is None for token in tokens))
        self.assertIsNotNone(self.business.accounts.session(self.business.accounts.login('reader', self.password, 'synthetic')))

    def test_reset_changes_only_password_and_never_enables_disabled_user(self):
        _, headers, _ = self.admin()
        user = self.account()
        token = self.business.accounts.login('reader', self.password, 'synthetic')
        path = '/api/v1/admin/users/' + user['user_id']
        self.client.patch(path, headers=headers, json={'enabled': False})
        before = self.row(user)
        response = self.client.post(path + '/password', headers=headers, json={'new_password': self.new_password})
        self.assertEqual(response.status_code, 204, response.text)
        after = self.row(user)
        self.assertNotEqual(after.pop('password_hash'), before.pop('password_hash'))
        self.assertEqual(after, before)
        self.assertIsNone(self.business.accounts.session(token))
        with self.assertRaises(TaskError):
            self.business.accounts.login('reader', self.new_password, 'synthetic')
        self.client.patch(path, headers=headers, json={'enabled': True})
        self.assertIsNotNone(self.business.accounts.session(self.business.accounts.login('reader', self.new_password, 'synthetic')))

    def test_delete_keeps_tasks_audit_input_bytes_and_recreation_has_new_identity(self):
        _, headers, _ = self.admin()
        user = self.account()
        token = self.business.accounts.login('reader', self.password, 'synthetic')
        self.business.store.create_batch([dict(data=self.image, name='synthetic.png', mime='image/png', actual_source_page_count=1)], 'DIPLOMA', user['user_id'])
        with self.business.engine.connect() as c:
            task_rows = c.execute(text('SELECT * FROM tasks')).all()
            audit_rows = c.execute(text('SELECT * FROM audit')).all()
        inputs = {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'data').rglob('*') if p.is_file() and 'sqlite' not in p.name}
        response = self.client.delete('/api/v1/admin/users/' + user['user_id'], headers=headers)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertIsNone(self.row(user))
        self.assertIsNone(self.business.accounts.session(token))
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT * FROM tasks')).all(), task_rows)
            self.assertEqual(c.execute(text('SELECT * FROM audit')).all(), audit_rows)
        self.assertTrue(all((self.root / p).read_bytes() == data for p, data in inputs.items()))
        self.assertNotEqual(self.account()['user_id'], user['user_id'])
        self.assertTrue(self.business.accounts.configured())
        self.assertIsNone(self.business.accounts.authenticate(self.headers['X-API-Key']))

    def test_all_roles_change_own_password_and_wrong_old_password_keeps_session(self):
        for role in ['viewer', 'operator', 'admin']:
            with self.subTest(role=role):
                self.account(role, role)
                headers = self.login(role)
                token = self.client.cookies.get('ocr_session')
                other_token = self.business.accounts.login(role, self.password, 'synthetic')
                response = self.client.post('/api/v1/auth/password', headers=headers,
                    json={'current_password': 'incorrect synthetic password', 'new_password': self.new_password})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()['code'], 'CURRENT_PASSWORD_INCORRECT')
                self.assertIsNotNone(self.business.accounts.session(token))
                response = self.client.post('/api/v1/auth/password', headers=headers,
                    json={'current_password': self.password, 'new_password': self.new_password})
                self.assertEqual(response.status_code, 204, response.text)
                self.assertIn('Max-Age=0', response.headers['set-cookie'])
                self.assertTrue(all(self.business.accounts.session(t) is None for t in [token, other_token]))
                self.assertEqual(self.client.get('/api/v1/auth/me').status_code, 401)
                self.assertIsNotNone(self.business.accounts.session(self.business.accounts.login(role, self.new_password, 'synthetic')))

    def test_admin_self_disable_delete_and_reset_are_rejected(self):
        admin, headers, _ = self.admin()
        self.account('second-admin', 'admin')
        path = '/api/v1/admin/users/' + admin['user_id']
        before = self.row(admin)
        for response in [self.client.patch(path, headers=headers, json={'enabled': False}),
                         self.client.delete(path, headers=headers),
                         self.client.post(path + '/password', headers=headers, json={'new_password': self.new_password})]:
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['code'], 'ACCOUNT_PROTECTED')
        self.assertEqual(self.row(admin), before)

    def test_permissions_csrf_origin_and_missing_targets(self):
        user = self.account()
        path = '/api/v1/admin/users/' + user['user_id']
        actions = [(self.client.patch, path, {'enabled': False}),
                   (self.client.delete, path, None),
                   (self.client.post, path + '/password', {'new_password': self.new_password})]
        def call(method, url, body, headers):
            return method(url, headers=headers, **({'json': body} if body is not None else {}))
        for method, url, body in actions:
            self.assertEqual(call(method, url, body, self.origin).status_code, 401)
        for role in ['viewer', 'operator']:
            self.account(role, role)
            headers = self.login(role)
            for method, url, body in actions:
                self.assertEqual(call(method, url, body, headers).status_code, 403)
        _, headers, _ = self.admin()
        for method, url, body in actions:
            self.assertEqual(call(method, url, body, self.origin).status_code, 403)
            self.assertEqual(call(method, url, body, dict(headers, Origin='http://foreign.invalid')).status_code, 403)
            self.assertEqual(call(method, url.replace(user['user_id'], str(uuid.uuid4())), body, headers).status_code, 404)
        for bad_headers in [self.origin, dict(headers, Origin='http://foreign.invalid')]:
            self.assertEqual(self.client.post('/api/v1/auth/password', headers=bad_headers,
                json={'current_password': self.password, 'new_password': self.new_password}).status_code, 403)

    def test_invalid_or_oversized_payloads_never_change_account(self):
        admin, headers, _ = self.admin()
        user = self.account()
        path = '/api/v1/admin/users/' + user['user_id']
        before = self.row(user)
        for payload in [{}, {'enabled': 1}, {'enabled': 'false'}, {'enabled': False, 'role': 'admin'}]:
            self.assertEqual(self.client.patch(path, headers=headers, json=payload).status_code, 422)
        for payload in [{}, {'new_password': 'short'}, {'new_password': 12}, {'new_password': ' '*8},
                        {'new_password': 'x'*129}, {'new_password': self.new_password, 'enabled': True}]:
            response = self.client.post(path + '/password', headers=headers, json=payload)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn(self.new_password, response.text)
        self.assertEqual(self.client.post(path + '/password', headers=headers, content=b'x'*8193).status_code, 413)
        for payload in [{}, {'current_password': 4, 'new_password': self.new_password},
                        {'current_password': self.password, 'new_password': 'short'},
                        {'current_password': self.password, 'new_password': self.new_password, 'extra': True}]:
            self.assertEqual(self.client.post('/api/v1/auth/password', headers=headers, json=payload).status_code, 422)
        self.assertEqual(self.row(user), before)

    def test_concurrent_admin_disable_keeps_one_enabled_admin(self):
        first, _, first_token = self.admin()
        second = self.account('second', 'admin')
        second_token = self.business.accounts.login('second', self.password, 'synthetic')
        barrier = threading.Barrier(2)
        def disable(args):
            actor, target, token = args
            barrier.wait()
            try:
                self.business.accounts.update_enabled(actor['user_id'], target['user_id'], False, token)
                return 'ok'
            except TaskError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(disable, [(first, second, first_token), (second, first, second_token)]))
        self.assertCountEqual(outcomes, ['ok', 'UNAUTHORIZED'])
        self.assertEqual(sum(u['enabled'] and u['role'] == 'admin' for u in self.business.accounts.users()), 1)

    def test_self_change_cannot_overwrite_concurrent_admin_reset(self):
        admin, _, _ = self.admin()
        admin_token = self.business.accounts.login('admin', self.password, 'synthetic admin browser')
        user = self.account()
        headers = self.login('reader')
        original_hash = self.business.accounts.hasher.hash
        def interrupt_hash(password):
            if password == self.new_password:
                self.business.accounts.reset_password(admin['user_id'], user['user_id'], 'concurrent admin replacement', admin_token)
            return original_hash(password)
        with patch.object(type(self.business.accounts.hasher), 'hash', side_effect=interrupt_hash):
            response = self.client.post('/api/v1/auth/password', headers=headers,
                json={'current_password': self.password, 'new_password': self.new_password})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertTrue(self.business.accounts.hasher.verify(self.row(user)['password_hash'], 'concurrent admin replacement'))

    def test_delete_failure_rolls_back_session_revocation(self):
        _, headers, _ = self.admin()
        user = self.account()
        token = self.business.accounts.login('reader', self.password, 'synthetic')
        def fail_delete(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('DELETE FROM web_users'):
                raise RuntimeError('synthetic transaction failure')
        event.listen(self.business.engine, 'before_cursor_execute', fail_delete)
        try:
            response = self.client.delete('/api/v1/admin/users/' + user['user_id'], headers=headers)
            self.assertEqual(response.status_code, 500)
        finally:
            event.remove(self.business.engine, 'before_cursor_execute', fail_delete)
        self.assertIsNotNone(self.row(user))
        self.assertIsNotNone(self.business.accounts.session(token))

    def test_create_rechecks_admin_session_after_hashing(self):
        first, headers, _ = self.admin()
        second = self.account('second', 'admin')
        token = self.business.accounts.login('second', self.password, 'synthetic second admin')
        original_hash = self.business.accounts.hasher.hash
        def disable_during_hash(password):
            if password == self.new_password:
                self.business.accounts.update_enabled(second['user_id'], first['user_id'], False, token)
            return original_hash(password)
        with patch.object(type(self.business.accounts.hasher), 'hash', side_effect=disable_during_hash):
            response = self.client.post('/api/v1/admin/users', headers=headers,
                json=dict(username='never-created', display_name='合成用户', password=self.new_password))
        self.assertEqual(response.status_code, 401, response.text)
        self.assertFalse(any(user['username'] == 'never-created' for user in self.business.accounts.users()))


if __name__ == '__main__':
    unittest.main()
