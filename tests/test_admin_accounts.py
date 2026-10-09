"""Administrator creation must never act as an account reset."""
import concurrent.futures
import unittest
from sqlalchemy import text
import test_business_api as base
from ocr_app.task_store import TaskError


class AdminAccountTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    origin = {'Origin': 'http://127.0.0.1'}
    password = 'synthetic admin credential'
    payload = dict(username='Reader', password='test1234', display_name='合成只读', role='viewer')

    def login(self, role='admin'):
        self.business.accounts.set_user('admin', self.password, '合成管理员', role)
        response = self.client.post('/api/v1/auth/login', headers=self.origin,
                                    json=dict(username='ADMIN', password=self.password))
        self.assertEqual(response.status_code, 200, response.text)
        return dict(self.origin, **{'X-CSRF-Token': response.json()['csrf_token']})

    def test_admin_creates_eight_character_account_and_new_user_can_login(self):
        headers = self.login()
        response = self.client.post('/api/v1/admin/users', headers=headers, json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        user = response.json()
        self.assertEqual(set(user), {'user_id', 'username', 'display_name', 'role', 'enabled'})
        self.assertEqual((user['username'], user['role'], user['enabled']), ('reader', 'viewer', True))
        users = self.client.get('/api/v1/admin/users').json()['items']
        self.assertEqual([row['username'] for row in users], ['admin', 'reader'])
        self.assertNotIn('password', str(users))
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=headers).status_code, 204)
        response = self.client.post('/api/v1/auth/login', headers=self.origin,
                                   json=dict(username='READER', password=self.payload['password']))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['role'], 'viewer')
        self.assertEqual(self.client.get('/api/v1/admin/users').status_code, 403)

    def test_duplicates_never_reset_password_permissions_or_session(self):
        headers = self.login()
        before = self.client.cookies.get('ocr_session')
        with self.business.engine.connect() as c:
            row = dict(c.execute(text('SELECT * FROM web_users WHERE username=\'admin\'')).mappings().one())
        response = self.client.post('/api/v1/admin/users', headers=headers,
                                   json=dict(self.payload, username='AdMiN', role='viewer'))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['code'], 'USERNAME_EXISTS')
        self.assertEqual(self.business.accounts.session(before)['role'], 'admin')
        with self.business.engine.connect() as c:
            self.assertEqual(dict(c.execute(text('SELECT * FROM web_users WHERE username=\'admin\'')).mappings().one()), row)

    def test_only_admin_and_valid_csrf_origin_can_create(self):
        self.assertEqual(self.client.get('/api/v1/admin/users').status_code, 401)
        for role in ['operator', 'viewer']:
            headers = self.login(role)
            self.assertEqual(self.client.get('/api/v1/admin/users').status_code, 403)
            self.assertEqual(self.client.post('/api/v1/admin/users', headers=headers, json=self.payload).status_code, 403)
        headers = self.login()
        self.assertEqual(self.client.post('/api/v1/admin/users', headers=self.origin, json=self.payload).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/admin/users', headers=dict(headers, Origin='http://foreign.invalid'), json=self.payload).status_code, 403)

    def test_invalid_and_oversized_creation_is_safe_and_default_is_operator(self):
        headers = self.login()
        for changes in [dict(password='test123'), dict(username='invalid name'), dict(role='owner'), dict(role=[]), dict(password=12), dict(display_name=''), dict(extra='unexpected')]:
            payload = dict(self.payload, **changes)
            response = self.client.post('/api/v1/admin/users', headers=headers, json=payload)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn('test123', response.text)
        response = self.client.post('/api/v1/admin/users', headers=headers, content=b'x'*8193)
        self.assertEqual(response.status_code, 413)
        payload = dict(self.payload); payload.pop('role')
        self.assertEqual(self.client.post('/api/v1/admin/users', headers=headers, json=payload).json()['role'], 'operator')

    def test_concurrent_duplicate_creates_exactly_one_account(self):
        def create(_):
            try:
                self.business.accounts.set_user('same', 'test1234', '合成用户', create_only=True)
                return 'created'
            except TaskError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(create, range(2))), ['created', 'USERNAME_EXISTS'])
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM web_users')).scalar_one(), 1)


if __name__ == '__main__':
    unittest.main()
