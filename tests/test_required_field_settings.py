"""Shared policy must agree across historical results, review and atomic export."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
import threading
import unittest

from sqlalchemy import text
import test_business_api as base
from ocr_app.business import Business
from ocr_app.auth import csrf_for
from ocr_app.extraction import extract_result
from ocr_app.required_fields import save_configuration
from ocr_app.task_store import TaskError


class RequiredFieldSettingsTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    origin = {'Origin': 'http://127.0.0.1'}

    def admin(self, role='admin'):
        self.business.accounts.set_user('admin', 'synthetic123', '合成管理员', role)
        response = self.client.post('/api/v1/auth/login', headers=self.origin,
                                    json=dict(username='admin', password='synthetic123'))
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = dict(self.origin, **{'X-CSRF-Token': response.json()['csrf_token']})
        return self.headers

    def save(self, kind, selected, revision=None):
        if revision is None:
            revision = self.business.store.required_policy()['revision']
        return self.client.put('/api/v1/admin/required-fields', headers=self.headers,
                               json=dict(doc_type=kind, required_fields=selected, expected_revision=revision))

    def ready(self, kind='DIPLOMA', values=None, result_extra=None):
        created = self.business.store.create_batch([dict(data=self.image, name='synthetic.png', mime='image/png')], kind, 'test')
        result = extract_result([], kind)
        for field in result['fields']:
            if field['key'] in (values or {}):
                field['value'] = values[field['key']]
        result.update(status='NEED_REVIEW', pages=[], **(result_extra or {}))
        self.assertTrue(self.business.store.publish(self.business.store.claim_next(), result))
        return self.business.store.task(created['task_ids'][0])

    def export(self, **selection):
        return self.client.post('/api/v1/export', headers=self.headers, json=dict(selection, format='xlsx', masked=False))

    def test_only_admin_and_valid_csrf_origin_can_read_or_save(self):
        self.assertEqual(self.client.get('/api/v1/admin/required-fields').status_code, 401)
        for role in ('operator', 'viewer'):
            self.admin(role)
            self.assertEqual(self.client.get('/api/v1/admin/required-fields').status_code, 403)
            self.assertEqual(self.save('DIPLOMA', []).status_code, 403)
        self.admin()
        body = dict(doc_type='DIPLOMA', required_fields=[], expected_revision=0)
        self.assertEqual(self.client.put('/api/v1/admin/required-fields', headers=self.origin, json=body).status_code, 403)
        self.assertEqual(self.client.put('/api/v1/admin/required-fields', headers=dict(self.headers, Origin='http://foreign.invalid'), json=body).status_code, 403)
        self.assertEqual(self.business.store.required_policy()['revision'], 0)

    def test_defaults_persist_and_reset_preserves_other_document_types(self):
        self.admin()
        initial = self.client.get('/api/v1/admin/required-fields').json()
        self.assertEqual(initial['revision'], 0)
        self.assertTrue(all(item['uses_defaults'] for item in initial['items']))
        self.assertEqual(self.save('DIPLOMA', ['name']).status_code, 200)
        self.assertEqual(self.save('MEDICAL_REPORT', ['name', 'institution']).status_code, 200)
        fresh = Business(self.root / 'data', key=b'T' * 32)
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.store.required_policy(), self.business.store.required_policy())
        self.assertEqual(self.save('DIPLOMA', None).status_code, 200)
        policy = self.business.store.required_policy()
        self.assertNotIn('DIPLOMA', policy['overrides'])
        self.assertEqual(policy['overrides']['MEDICAL_REPORT'], ['name', 'institution'])
        revision = policy['revision']
        self.assertEqual(self.save('DIPLOMA', None).json()['revision'], revision)

    def test_streamed_save_rechecks_revoked_session_even_for_noop(self):
        accounts = self.business.accounts
        controller = accounts.set_user('controller', 'synthetic123', '合成管理者', 'admin')
        controller_token = accounts.login('controller', 'synthetic123', 'synthetic-controller')
        for name, selected in [('disabled', []), ('logged-out-noop', None)]:
            with self.subTest(revocation=name):
                actor = accounts.set_user(name, 'synthetic123', '合成操作者', 'admin')
                token = accounts.login(name, 'synthetic123', 'synthetic-' + name)
                self.client.cookies.clear()
                self.client.cookies.set('ocr_session', token)
                entered, release = threading.Event(), threading.Event()
                policy = self.business.store.required_policy()
                payload = json.dumps(dict(doc_type='DIPLOMA', required_fields=selected,
                                          expected_revision=policy['revision'])).encode()

                def slow_body():
                    yield payload[:1]
                    entered.set()
                    if not release.wait(10):
                        raise TimeoutError('synthetic body was not released')
                    yield payload[1:]

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.client.put, '/api/v1/admin/required-fields',
                        headers=dict(self.origin, **{'X-CSRF-Token': csrf_for(token), 'Content-Type': 'application/json'}),
                        content=slow_body())
                    try:
                        self.assertTrue(entered.wait(8), 'request did not reach body reading')
                        if name == 'disabled':
                            accounts.update_enabled(controller['user_id'], actor['user_id'], False, controller_token)
                        else:
                            accounts.logout(token)
                        self.assertIsNone(accounts.session(token))
                    finally:
                        release.set()
                    response = future.result(timeout=10)
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(self.business.store.required_policy(), policy)
                with self.business.engine.connect() as connection:
                    self.assertEqual(connection.execute(text(
                        "SELECT count(*) FROM audit WHERE event='required_fields_changed'")).scalar_one(), 0)

    def test_unknown_duplicate_nonstring_and_derived_fields_are_rejected(self):
        self.admin()
        body = dict(doc_type='DIPLOMA', required_fields=['name'], expected_revision=0)
        for patch in (dict(required_fields=['unknown']), dict(required_fields=[1]), dict(required_fields=['name', 'name']),
                      dict(required_fields=True), dict(doc_type='UNKNOWN'), dict(doc_type=[]), dict(expected_revision=True),
                      dict(extra='unexpected'), dict(doc_type='MEDICAL_REPORT', required_fields=['exam_project_count'])):
            with self.subTest(patch=patch):
                response = self.client.put('/api/v1/admin/required-fields', headers=self.headers, json=dict(body, **patch))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.business.store.required_policy()['revision'], 0)

    def test_historical_flags_and_review_use_current_policy_without_rewriting_ciphertext(self):
        task = self.ready(values=dict(name='合成人员'))
        self.admin()
        with self.business.engine.connect() as c:
            before = dict(c.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task['task_id']}).mappings().one())
        self.assertFalse(task['export_ready'])
        self.assertEqual(self.save('DIPLOMA', ['name']).status_code, 200)
        updated = self.business.store.task(task['task_id'])
        self.assertTrue(updated['export_ready'])
        self.assertEqual(updated['result_revision'], task['result_revision'])
        result = self.business.store.result(task['task_id'])
        school = next(field for field in result['fields'] if field['key'] == 'school_name')
        self.assertFalse(school['required'])
        self.assertFalse(any(p['code'] == 'MISSING' for p in school['review_issues']))
        self.assertEqual(result['required_field_keys'], ['name'])
        self.assertEqual(updated['required_fields_revision'], result['required_fields_revision'])
        with self.business.engine.connect() as c:
            self.assertEqual(dict(c.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task['task_id']}).mappings().one()), before)
        response = self.client.post(f"/api/v1/tasks/{task['task_id']}/review", headers=self.headers,
            json=dict(run_id=task['run_id'], expected_revision=task['result_revision'], absence_reasons={'school_name': 'NOT_ON_DOCUMENT'}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.save('DIPLOMA', ['name', 'school_name']).status_code, 200)
        self.assertFalse(self.business.store.task(task['task_id'])['export_ready'])
        self.assertTrue(next(f for f in self.business.store.result(task['task_id'])['fields'] if f['key']=='school_name')['required'])

    def test_batch_export_uses_one_latest_policy_and_never_exports_partial_selection(self):
        first = self.ready(values=dict(name='合成人员'))
        second = self.ready()
        self.admin()
        self.assertEqual(self.save('DIPLOMA', ['name']).status_code, 200)
        response = self.export(task_ids=[first['task_id'], second['task_id']])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['code'], 'EXPORT_BLOCKED')
        self.assertEqual(len(response.json()['details']['tasks']), 1)
        self.assertEqual(self.save('DIPLOMA', []).status_code, 200)
        self.assertEqual(self.export(task_ids=[first['task_id'], second['task_id']]).status_code, 200)
        self.assertEqual(self.business.store.task(first['task_id'])['result_revision'], first['result_revision'])
        pending = self.business.store.create_batch([dict(data=b'pending', name='pending.png', mime='image/png')], 'DIPLOMA', 'test')
        self.assertFalse(self.business.store.task(pending['task_ids'][0])['export_ready'])
        self.assertEqual(self.export(batch_id=pending['batch_id']).status_code, 409)

    def test_household_members_and_generic_text_share_the_policy(self):
        from ocr_app.extraction import _field
        member = {'name': _field('name', '姓名', [], True)}
        member['name']['value'] = '合成人员'
        task = self.ready('HOUSEHOLD_REGISTER', result_extra=dict(members=[member]))
        self.admin()
        self.assertEqual(self.save('HOUSEHOLD_REGISTER', ['members.name', 'members.gender']).status_code, 200)
        result = self.business.store.result(task['task_id'])
        self.assertEqual(result['export_blockers'], [dict(field='members[0].gender', code='MISSING')])
        self.assertTrue(result['members'][0]['gender']['required'])
        generic = self.ready('GENERIC')
        self.assertFalse(generic['export_ready'])
        self.assertEqual(self.save('GENERIC', []).status_code, 200)
        self.assertTrue(self.business.store.task(generic['task_id'])['export_ready'])
        response = self.client.post(f"/api/v1/tasks/{generic['task_id']}/review", headers=self.headers,
            json=dict(run_id=generic['run_id'], expected_revision=generic['result_revision'], generic={'full_text':'', 'key_values':[]}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.save('GENERIC', None).status_code, 200)
        self.assertFalse(self.business.store.task(generic['task_id'])['export_ready'])

    def test_concurrent_administrators_cannot_lose_updates(self):
        def save(kind):
            try:
                return save_configuration(self.business.store, dict(doc_type=kind, required_fields=['name'], expected_revision=0),
                                          'test', authorize=lambda connection: None)['revision']
            except TaskError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(save, ('DIPLOMA', 'MEDICAL_REPORT'))), [1, 'SETTINGS_VERSION_CONFLICT'])
        self.assertEqual(len(self.business.store.required_policy()['overrides']), 1)

    def test_batch_list_uses_one_policy_snapshot_during_concurrent_setting_change(self):
        self.ready(); self.ready()
        store = self.business.store
        original = store.batch
        def concurrent_save(identifier, *, policy=None, user=None):
            if store.required_policy()['revision'] == 0:
                save_configuration(store, dict(doc_type='DIPLOMA', required_fields=[], expected_revision=0),
                                   'test', authorize=lambda connection: None)
            return original(identifier, policy=policy, user=user)
        with patch.object(store, 'batch', side_effect=concurrent_save):
            listed = store.batches()
        self.assertEqual([batch['required_fields_revision'] for batch in listed['items']], [0, 0])
        self.assertEqual([batch['required_fields_revision'] for batch in store.batches()['items']], [1, 1])


if __name__ == '__main__':
    unittest.main()
