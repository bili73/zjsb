"""Account isolation uses synthetic material, temporary databases and no models."""
from pathlib import Path
import tempfile
import uuid
import unittest
from sqlalchemy import create_engine, text
from alembic import command
from alembic.config import Config

import test_business_api as base
from ocr_app.auth import csrf_for
from ocr_app.extraction import extract_result
from ocr_app.db import open_database


class BatchOwnershipTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    password = 'synthetic account password'

    def account(self, name, role='operator'):
        account = self.business.accounts.set_user(name, self.password, '姓名 ' + name, role)
        token = self.business.accounts.login(name, self.password, 'synthetic-' + name)
        headers = {'Cookie': 'ocr_session=' + token, 'Origin': 'http://127.0.0.1', 'X-CSRF-Token': csrf_for(token)}
        return account, headers, token

    def batch(self, account, status='NEED_REVIEW'):
        created = self.business.store.create_batch([dict(data=self.image, name='synthetic.png',
            mime='image/png', actual_source_page_count=1)], 'DIPLOMA', account['user_id'])
        task = self.business.store.task(created['task_ids'][0])
        result = extract_result([], 'DIPLOMA')
        for field in result['fields']:
            field.update(value='synthetic value', need_review=False, review_issues=[])
        result.update(status=status, review_issues=[])
        with self.business.store.transaction() as c:
            c.execute(text('UPDATE tasks SET status=:status,result_enc=:result WHERE id=:id'),
                      dict(status=status, result=self.business.storage.pack(result), id=task['task_id']))
            reference = self.business.storage.put(self.image)
            c.execute(text("INSERT INTO artifacts(id,task_id,run_id,kind,page_index,reference) "
                           "VALUES (:id,:task,:run,'corrected',1,:ref)"),
                      dict(id=str(uuid.uuid4()), task=task['task_id'], run=task['run_id'], ref=reference))
        return created['batch_id'], self.business.store.task(task['task_id'])

    def snapshot(self):
        with self.business.engine.connect() as c:
            return {table: c.execute(text('SELECT * FROM ' + table + ' ORDER BY id')).all()
                    for table in ['tasks', 'runs', 'artifacts', 'audit', 'batches']}

    def test_lists_are_scoped_before_dates_totals_and_pagination(self):
        alice, ah, _ = self.account('alice')
        bob, bh, _ = self.account('bob')
        _, admin_headers, _ = self.account('admin', 'admin')
        own = [self.batch(alice)[0] for _ in range(2)]
        foreign = self.batch(bob)[0]
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE batches SET created_at='2026-10-09T17:00:00+00:00'"))
        for headers, expected in [(ah, own), (bh, [foreign]), (admin_headers, own + [foreign])]:
            path = '/api/v1/batches?date_from=2026-10-10&date_to=2026-10-10&page_size=1'
            first = self.client.get(path, headers=headers).json()
            self.assertEqual(first['total'], len(expected))
            ids = []
            for page in range(1, len(expected) + 1):
                ids.extend(b['batch_id'] for b in self.client.get(path + '&page=' + str(page), headers=headers).json()['items'])
            self.assertCountEqual(ids, expected)
            tasks = self.client.get('/api/v1/tasks', headers=headers).json()
            self.assertEqual(tasks['total'], len(expected))
            self.assertEqual({t['batch_id'] for t in tasks['items']}, set(expected))

    def test_every_foreign_task_and_batch_route_is_denied_without_side_effects(self):
        alice, ah, _ = self.account('alice')
        bob, _, _ = self.account('bob')
        batch, task = self.batch(bob)
        queued_batch, queued = self.batch(bob, 'QUEUED')
        prefix = '/api/v1/tasks/' + task['task_id']
        version = dict(run_id=task['run_id'], expected_revision=task['result_revision'])
        calls = [
            ('GET', '/api/v1/batches/' + batch, None),
            ('GET', '/api/v1/batches/' + batch + '/tasks', None),
            ('GET', prefix, None), ('GET', prefix + '/result', None),
            ('GET', prefix + '/preview?run_id=' + task['run_id'] + '&result_revision=0&page=1', None),
            ('POST', prefix + '/preview', dict(version, page=1)),
            ('POST', prefix + '/reveal', dict(version, fields=['certificate_no'], reason='synthetic check')),
            ('POST', prefix + '/review', dict(version, fields={'name': 'synthetic correction'})),
            ('POST', prefix + '/rerun', version),
            ('POST', '/api/v1/tasks/' + queued['task_id'] + '/cancel',
             dict(run_id=queued['run_id'], expected_revision=0)),
            ('POST', '/api/v1/export', dict(batch_id=batch)),
        ]
        before = self.snapshot()
        for method, path, body in calls:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, headers=ah, **({'json': body} if body is not None else {}))
                self.assertEqual(response.status_code, 404, response.text)
                self.assertNotIn('synthetic value', response.text)
                self.assertEqual(self.snapshot(), before)
        missing = self.client.get('/api/v1/tasks/' + str(uuid.uuid4()), headers=ah)
        foreign = self.client.get(prefix, headers=ah)
        self.assertEqual((missing.status_code, missing.json()['code'], missing.json()['message']),
                         (foreign.status_code, foreign.json()['code'], foreign.json()['message']))

    def test_owner_and_admin_read_preview_export_and_admin_review_preserves_owner(self):
        alice, ah, _ = self.account('alice')
        _, admin_headers, _ = self.account('admin', 'admin')
        batch, task = self.batch(alice)
        for headers in [ah, admin_headers]:
            self.assertEqual(self.client.get('/api/v1/tasks/' + task['task_id'] + '/result', headers=headers).status_code, 200)
            self.assertEqual(self.client.get('/api/v1/tasks/' + task['task_id'] + '/preview?run_id=' + task['run_id'] + '&result_revision=0', headers=headers).status_code, 200)
            self.assertEqual(self.client.post('/api/v1/export', headers=headers, json=dict(batch_id=batch)).status_code, 200)
        response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/review', headers=admin_headers,
            json=dict(run_id=task['run_id'], expected_revision=0, fields={'name': 'synthetic reviewed name'}))
        self.assertEqual(response.status_code, 200, response.text)
        owner = self.client.get('/api/v1/batches/' + batch, headers=admin_headers).json()['owner']
        self.assertEqual(owner['user_id'], alice['user_id'])

    def test_mixed_export_is_atomic_and_duplicate_warning_does_not_leak_other_owner(self):
        alice, ah, _ = self.account('alice')
        bob, bh, _ = self.account('bob')
        _, ta = self.batch(alice)
        _, tb = self.batch(bob)
        self.assertEqual(tb['warnings'], [])
        _, repeated = self.batch(bob)
        self.assertTrue(any(w['code'] == 'DUPLICATE_FILE' for w in repeated['warnings']))
        for headers, ids in [(ah, [ta['task_id'], tb['task_id']]), (bh, [tb['task_id'], ta['task_id']])]:
            before = self.snapshot()
            response = self.client.post('/api/v1/export', headers=headers, json=dict(task_ids=ids))
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(before, self.snapshot())

    def test_viewer_is_scoped_and_still_readonly(self):
        viewer, vh, _ = self.account('viewer', 'viewer')
        alice, _, _ = self.account('alice')
        own, task = self.batch(viewer)
        foreign, _ = self.batch(alice)
        listed = self.client.get('/api/v1/batches', headers=vh).json()
        self.assertEqual([b['batch_id'] for b in listed['items']], [own])
        self.assertEqual(self.client.get('/api/v1/batches/' + foreign, headers=vh).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/tasks/' + task['task_id'] + '/result', headers=vh).status_code, 200)
        self.assertEqual(self.client.post('/api/v1/export', headers=vh, json=dict(batch_id=own)).status_code, 403)

    def test_upload_owner_is_authenticated_identity_and_cannot_be_supplied(self):
        alice, ah, _ = self.account('alice')
        response = self.client.post('/api/v1/batches', headers=ah, files={'files': ('synthetic.png', self.image)},
                                   data={'doc_type_hint': 'DIPLOMA'})
        self.assertEqual(response.status_code, 202, response.text)
        batch = self.client.get('/api/v1/batches/' + response.json()['batch_id'], headers=ah).json()
        self.assertEqual(batch['owner']['user_id'], alice['user_id'])
        malicious = self.client.post('/api/v1/batches', headers=ah, files={'files': ('synthetic.png', self.image)},
                                    data={'doc_type_hint': 'DIPLOMA', 'owner_id': str(uuid.uuid4())})
        self.assertEqual(malicious.status_code, 400)

    def test_deleted_identity_keeps_name_and_recreated_username_cannot_inherit(self):
        alice, _, _ = self.account('alice')
        _, admin_headers, _ = self.account('admin', 'admin')
        batch, _ = self.batch(alice)
        changed = self.client.patch('/api/v1/admin/users/' + alice['user_id'], headers=admin_headers,
                                    json={'display_name': '更新后的姓名'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(self.client.delete('/api/v1/admin/users/' + alice['user_id'], headers=admin_headers).status_code, 204)
        replacement, rh, _ = self.account('alice')
        self.assertNotEqual(replacement['user_id'], alice['user_id'])
        self.assertEqual(self.client.get('/api/v1/batches/' + batch, headers=rh).status_code, 404)
        owner = self.client.get('/api/v1/batches/' + batch, headers=admin_headers).json()['owner']
        self.assertEqual(owner, dict(user_id=alice['user_id'], username='alice', display_name='更新后的姓名', account_exists=False))

    def test_name_edit_preserves_credential_role_state_and_sessions(self):
        alice, ah, token = self.account('alice')
        admin, admin_headers, _ = self.account('admin', 'admin')
        batch, _ = self.batch(alice)
        with self.business.engine.connect() as c:
            original = dict(c.execute(text('SELECT * FROM web_users WHERE id=:id'), {'id': alice['user_id']}).mappings().one())
        response = self.client.patch('/api/v1/admin/users/' + alice['user_id'], headers=admin_headers, json={'display_name': '  修改姓名  '})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['display_name'], '修改姓名')
        with self.business.engine.connect() as c:
            current = dict(c.execute(text('SELECT * FROM web_users WHERE id=:id'), {'id': alice['user_id']}).mappings().one())
        self.assertEqual(current, dict(original, display_name='修改姓名'))
        self.assertEqual(self.business.accounts.session(token)['display_name'], '修改姓名')
        self.assertEqual(self.client.get('/api/v1/batches/' + batch, headers=ah).json()['owner']['display_name'], '修改姓名')
        self.assertEqual(self.client.patch('/api/v1/admin/users/' + admin['user_id'], headers=admin_headers,
                                         json={'display_name': '管理员新姓名'}).status_code, 200)
        for body in [{'display_name': ''}, {'display_name': ' '}, {'display_name': 1}, {'display_name': 'a\nb'},
                     {'display_name': 'x' * 81}, {'display_name': 'ok', 'role': 'admin'}, {'display_name': 'ok', 'enabled': False}]:
            self.assertEqual(self.client.patch('/api/v1/admin/users/' + alice['user_id'], headers=admin_headers, json=body).status_code, 422)
        self.assertEqual(self.client.patch('/api/v1/admin/users/' + alice['user_id'], headers=ah, json={'display_name': 'self'}).status_code, 403)
        self.assertEqual(self.client.patch('/api/v1/admin/users/' + alice['user_id'], headers={'Cookie': admin_headers['Cookie'], 'Origin': 'http://127.0.0.1'}, json={'display_name': 'no csrf'}).status_code, 403)

    def test_unassigned_and_unmapped_history_is_admin_only(self):
        alice, ah, _ = self.account('alice')
        _, admin_headers, _ = self.account('admin', 'admin')
        for identifier in [None, str(uuid.uuid4())]:
            batch, task = self.batch(alice)
            with self.business.store.transaction() as c:
                c.execute(text('UPDATE batches SET owner_id=:owner,owner_snapshot_enc=NULL WHERE id=:id'), dict(owner=identifier, id=batch))
            self.assertEqual(self.client.get('/api/v1/batches/' + batch, headers=ah).status_code, 404)
            self.assertEqual(self.client.get('/api/v1/tasks/' + task['task_id'], headers=ah).status_code, 404)
            admin_view = self.client.get('/api/v1/batches/' + batch, headers=admin_headers)
            self.assertEqual(admin_view.status_code, 200)
            self.assertEqual(admin_view.json()['owner']['user_id'], identifier)

    def test_name_edit_rechecks_revoked_administrator_session(self):
        from ocr_app.task_store import TaskError
        alice, _, _ = self.account('alice')
        admin, _, token = self.account('admin', 'admin')
        self.business.accounts.logout(token)
        with self.assertRaises(TaskError) as caught:
            self.business.accounts.update_display_name(admin['user_id'], alice['user_id'], 'must not save', token)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(next(a for a in self.business.accounts.users() if a['user_id'] == alice['user_id'])['display_name'], alice['display_name'])


class BatchOwnerMigrationTests(unittest.TestCase):
    def test_additive_backfill_requires_complete_unambiguous_creation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'tasks.sqlite3'))
            config = Config()
            config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'backend/migrations'))
            with engine.begin() as c:
                config.attributes['connection'] = c
                command.upgrade(config, '0004')
                owner, legacy = str(uuid.uuid4()), str(uuid.uuid4())
                c.execute(text("INSERT INTO web_users VALUES (:id,'alice','synthetic','operator','not-a-real-hash',1)"), {'id': owner})
                cases = {'known': [owner, owner], 'legacy': [legacy], 'conflicting': [owner, legacy],
                         'missing': [owner, None], 'empty': []}
                for batch, actors in cases.items():
                    c.execute(text("INSERT INTO batches VALUES (:id,'2026-10-10T00:00:00+00:00',:name)"), dict(id=batch, name=b'unchanged batch cipher'))
                    for actor in actors:
                        task, run = str(uuid.uuid4()), str(uuid.uuid4())
                        c.execute(text("""INSERT INTO tasks(id,batch_id,run_id,status,created_at,updated_at,expires_at,
                            content_hash,doc_type,input_ref,meta_enc,options_enc,result_enc)
                            VALUES (:id,:batch,:run,'NEED_REVIEW','2026-10-10','2026-10-10','2026-10-17',
                            :id,'DIPLOMA','synthetic-ref',:blob,:blob,:blob)"""),
                                  dict(id=task, batch=batch, run=run, blob=b'unchanged encrypted bytes'))
                        if actor is not None:
                            c.execute(text("INSERT INTO audit VALUES (:id,:actor,:task,:run,'task_created','2026-10-10','{}')"),
                                      dict(id=str(uuid.uuid4()), actor=actor, task=task, run=run))
                before = {table: c.execute(text('SELECT * FROM ' + table + ' ORDER BY id')).all() for table in ['tasks', 'audit', 'web_users']}
            engine.dispose()
            upgraded = open_database(root)
            try:
                with upgraded.connect() as c:
                    self.assertEqual(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), '0008')
                    actual = dict(c.execute(text('SELECT id,owner_id FROM batches')).all())
                    self.assertEqual(actual, dict(known=owner, legacy=legacy, conflicting=None, missing=None, empty=None))
                    self.assertTrue(all(row[0] == b'unchanged batch cipher' for row in c.execute(text('SELECT name_enc FROM batches'))))
                    for table, rows in before.items():
                        self.assertEqual(c.execute(text('SELECT * FROM ' + table + ' ORDER BY id')).all(), rows)
                # Rerunning startup never reassigns identities from later audit changes.
                with upgraded.begin() as c:
                    c.execute(text("UPDATE audit SET actor='different-later-actor'"))
            finally:
                upgraded.dispose()
            reopened = open_database(root)
            try:
                with reopened.connect() as c:
                    self.assertEqual(dict(c.execute(text('SELECT id,owner_id FROM batches')).all()), actual)
            finally:
                reopened.dispose()


if __name__ == '__main__':
    unittest.main()
