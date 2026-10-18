"""Named sessions use synthetic credentials and isolated databases only."""
import hashlib
import unittest
from unittest.mock import patch
from sqlalchemy import text
import test_business_api as base
from ocr_app.task_store import TaskError


class WebSessionTests(unittest.TestCase):
    setUp=base.BusinessAPITests.setUp
    password='synthetic test password 2026'
    origin={'Origin':'http://127.0.0.1'}

    def provision(self):
        self.business.accounts.set_user('tester',self.password,'合成操作员','operator')

    def login(self, password=None):
        return self.client.post('/api/v1/auth/login',headers=self.origin,
                                json={'username':'tester','password':password or self.password})

    def test_cookie_restores_identity_and_logout_revokes(self):
        self.provision()
        response=self.login()
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertNotIn(self.password,response.text)
        me=self.client.get('/api/v1/auth/me').json()
        self.assertEqual(me['display_name'],'合成操作员')
        self.assertTrue(me['csrf_token'])
        self.assertEqual(self.client.get('/api/v1/doc-types').status_code,200)
        token=self.client.cookies.get('ocr_session')
        with self.business.engine.connect() as c:
            stored=c.execute(text('SELECT token_hash FROM web_sessions')).scalar_one()
        self.assertEqual(stored,hashlib.sha256(token.encode()).hexdigest())
        response=self.client.post('/api/v1/auth/logout',headers=dict(self.origin,**{'X-CSRF-Token':me['csrf_token']}))
        self.assertEqual(response.status_code,204,response.text)
        self.assertIsNone(self.business.accounts.session(token))
        self.assertEqual(self.client.get('/api/v1/doc-types').status_code,401)

    def test_origin_csrf_and_legacy_bypass_close_once_provisioned(self):
        self.provision()
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=self.headers).status_code,401)
        self.assertEqual(self.client.post('/api/v1/auth/login',json={'username':'tester','password':self.password}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/auth/login',headers={'Origin':'https://evil.example'},json={'username':'tester','password':self.password}).status_code,403)
        self.assertEqual(self.login().status_code,200)
        for path in ['/api/v1/auth/logout','/api/v1/export','/api/v1/batches']:
            self.assertEqual(self.client.post(path,headers=self.origin,json={}).status_code,403)
        me=self.client.get('/api/v1/auth/me').json()
        for h in [dict(self.origin,**{'X-CSRF-Token':'bad'}),{'Origin':'https://evil.example','X-CSRF-Token':me['csrf_token']}]:
            self.assertEqual(self.client.post('/api/v1/auth/logout',headers=h).status_code,403)

    def test_password_change_disable_expiration_and_rotation(self):
        self.provision();self.assertEqual(self.login().status_code,200)
        first=self.client.cookies.get('ocr_session')
        self.assertEqual(self.login().status_code,200)
        second=self.client.cookies.get('ocr_session')
        self.assertNotEqual(first,second)
        self.assertIsNone(self.business.accounts.session(first))
        self.business.accounts.set_user('tester','new synthetic password','合成操作员','operator')
        self.assertIsNone(self.business.accounts.session(second))
        self.assertEqual(self.login('new synthetic password').status_code,200)
        third=self.client.cookies.get('ocr_session')
        with patch('ocr_app.auth.time',return_value=10**12):
            self.assertIsNone(self.business.accounts.session(third))
        self.business.accounts.disable_user('tester')
        self.assertIsNone(self.business.accounts.session(third))
        self.assertEqual(self.login('new synthetic password').status_code,401)
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=self.headers).status_code,401)

    def test_failed_login_is_uniform_and_throttled(self):
        self.provision()
        for _ in range(5):
            response=self.login('wrong synthetic password')
            self.assertEqual(response.status_code,401)
            self.assertNotIn('tester',response.text)
            self.assertNotIn('wrong synthetic',response.text)
        self.assertEqual(self.login().status_code,429)
        with patch('ocr_app.auth.time',return_value=10**12):
            self.assertEqual(self.login().status_code,200)

    def test_reset_during_verification_cannot_create_obsolete_session(self):
        self.provision()
        hasher=self.business.accounts.hasher
        verify=hasher.verify
        def resetting(encoded,password):
            correct=verify(encoded,password)
            self.business.accounts.set_user('tester','changed synthetic password','合成操作员','operator')
            return correct
        with patch.object(type(hasher),'verify',side_effect=resetting):
            self.assertEqual(self.login().status_code,401)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM web_sessions')).scalar_one(),0)

    def test_password_policy_and_account_errors_have_no_secret(self):
        for user,password in [('invalid username',self.password),('tester','short')]:
            with self.assertRaises(TaskError):
                self.business.accounts.set_user(user,password,'name','operator')

    def test_https_cookie_restart_persistence_and_viewer_permissions(self):
        from ocr_app.auth import Accounts
        self.business.accounts.set_user('tester',self.password,'只读测试','viewer')
        response=self.client.post('https://127.0.0.1/api/v1/auth/login',headers={'Origin':'https://127.0.0.1'},
                                  json={'username':'tester','password':self.password})
        self.assertEqual(response.status_code,200)
        self.assertIn('Secure',response.headers['set-cookie'])
        token=self.client.cookies.get('ocr_session')
        reloaded=Accounts(self.business.storage,self.business.engine)
        self.assertEqual(reloaded.session(token)['role'],'viewer')
        me=self.client.get('https://127.0.0.1/api/v1/auth/me').json()
        self.assertEqual(me['permissions'],[])
        self.assertEqual(self.client.post('https://127.0.0.1/api/v1/export',
            headers={'Origin':'https://127.0.0.1','X-CSRF-Token':me['csrf_token']},json={'task_ids':['11111111-2222-4333-8444-555555555555']}).status_code,403)

    def test_named_review_and_export_preserve_revision_and_original_run(self):
        from test_review_api import ReviewAPITests,CERT
        self.upload=base.BusinessAPITests.upload.__get__(self)
        self.task=base.BusinessAPITests.task.__get__(self)
        self.provision();self.assertEqual(self.login().status_code,200)
        me=self.client.get('/api/v1/auth/me').json()
        self.headers=dict(self.origin,**{'X-CSRF-Token':me['csrf_token']})
        task,_=ReviewAPITests.ready(self)
        with self.business.engine.connect() as c:
            run=dict(c.execute(text('SELECT * FROM runs WHERE id=:id'),{'id':task['run_id']}).mappings().one())
        headers=dict(self.origin,**{'X-CSRF-Token':me['csrf_token']})
        response=self.client.post('/api/v1/tasks/'+task['task_id']+'/review',headers=headers,
                                 json=dict(run_id=task['run_id'],expected_revision=task['result_revision'],fields=CERT))
        self.assertEqual(response.status_code,200,response.text)
        revised=response.json()
        self.assertEqual(revised['result_revision'],task['result_revision']+1)
        export=self.client.post('/api/v1/export',headers=headers,json={'task_ids':[task['task_id']]})
        self.assertEqual(export.status_code,200)
        self.assertTrue(export.content.startswith(b'PK'))
        with self.business.engine.connect() as c:
            self.assertEqual(dict(c.execute(text('SELECT * FROM runs WHERE id=:id'),{'id':task['run_id']}).mappings().one()),run)
            self.assertEqual(c.execute(text("SELECT actor FROM audit WHERE event='export_generated'")).scalar_one(),me['user_id'])

if __name__=='__main__': unittest.main()
