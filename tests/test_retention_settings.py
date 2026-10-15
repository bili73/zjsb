"""Retention policy, irreversible cleanup boundaries and authorized confirmation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from sqlalchemy import text
import test_required_field_settings as base
from ocr_app.business import Business
from ocr_app.retention import load_policy, save_configuration
from ocr_app.task_store import TaskError


class RetentionSettingsTests(unittest.TestCase):
    setUp = base.RequiredFieldSettingsTests.setUp
    admin = base.RequiredFieldSettingsTests.admin
    ready = base.RequiredFieldSettingsTests.ready
    origin = base.RequiredFieldSettingsTests.origin

    def policy(self):
        with self.business.engine.connect() as c:
            return load_policy(c)

    def save(self, days, revision=None, **extra):
        return self.client.put('/api/v1/admin/retention', headers=self.headers, json=dict(
            days=days, expected_revision=self.policy()['revision'] if revision is None else revision,
            confirmed=True, **extra))

    def snapshot(self, task_id):
        with self.business.engine.connect() as c:
            return dict(c.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().one())

    def test_defaults_and_all_choices_recalculate_old_and_new_without_touching_results(self):
        self.admin()
        created = (datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
        with patch('ocr_app.task_store.now', return_value=created):
            old = self.ready(values=dict(name='synthetic'))
        before = self.snapshot(old['task_id'])
        self.assertEqual(self.policy(), dict(days=7, revision=0))
        for days in (15, 30, None, 7):
            with self.subTest(days=days):
                response = self.save(days)
                self.assertEqual(response.status_code, 200, response.text)
                current = self.business.store.task(old['task_id'])
                expected = (datetime.fromisoformat(created)+timedelta(days=days)).isoformat() if days else None
                self.assertEqual(current['expires_at'], expected)
                self.assertEqual(self.business.store.batch(old['batch_id'])['expires_at'], expected)
                after = self.snapshot(old['task_id'])
                self.assertEqual({k:v for k,v in before.items() if k != 'expires_at'},
                                 {k:v for k,v in after.items() if k != 'expires_at'})
                new = self.ready()
                expected_new = (datetime.fromisoformat(new['created_at'])+timedelta(days=days)).isoformat() if days else None
                self.assertEqual(new['expires_at'], expected_new)
        impact = self.client.get('/api/v1/admin/retention').json()['impact']
        self.assertEqual(impact[0]['eligible_count'], 1)
        self.assertEqual(impact[1]['eligible_count'], 0)

    def test_nullable_deadlines_and_policy_match_published_contract(self):
        from pathlib import Path
        import jsonschema
        import yaml
        from test_pipeline_schema import json_schema
        document=json_schema(yaml.safe_load((Path(__file__).resolve().parents[1]/'openapi.yaml').read_text(encoding='utf-8')))
        self.admin()
        task=self.ready()
        for days in (30,None):
            response=self.save(days)
            for name,value in [('RetentionSettings',response.json()),
                               ('Task',self.business.store.task(task['task_id'])),
                               ('Batch',self.business.store.batch(task['batch_id']))]:
                schema=document['components']['schemas'][name]
                if name != 'RetentionSettings':
                    schema,value=schema['properties']['expires_at'],value['expires_at']
                jsonschema.Draft7Validator(schema,format_checker=jsonschema.FormatChecker()).validate(value)

    def test_never_survives_restart_then_finite_cleanup_removes_history_but_not_accounts(self):
        self.admin()
        with patch('ocr_app.task_store.now', return_value='2020-01-01T00:00:00+00:00'):
            task = self.ready()
        self.assertEqual(self.save(None).status_code, 200)
        fresh = Business(self.root / 'data', key=b'T'*32)
        self.addCleanup(fresh.close)
        fresh.prepare()
        self.assertIsNone(fresh.store.task(task['task_id'])['expires_at'])
        self.assertEqual(self.save(15).status_code, 200)
        # A setting save does not synchronously delete the old file.
        self.assertIsNotNone(fresh.store.task(task['task_id']))
        fresh.store.cleanup()
        with self.business.engine.connect() as c:
            for table in ('tasks', 'batches', 'runs', 'artifacts', 'attempts'):
                self.assertEqual(c.execute(text('SELECT count(*) FROM '+table)).scalar_one(), 0)
            self.assertGreater(c.execute(text('SELECT count(*) FROM web_users')).scalar_one(), 0)
            self.assertEqual(c.execute(text("SELECT count(*) FROM audit WHERE event='retention_changed'")).scalar_one(), 2)
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_active_is_deferred_and_counts_explain_it(self):
        self.admin()
        with patch('ocr_app.task_store.now', return_value='2020-01-01T00:00:00+00:00'):
            created = self.business.store.create_batch([dict(data=self.image,name='synthetic.png',mime='image/png')], 'DIPLOMA','test')
        active = self.business.store.claim_next()
        self.save(30)
        self.business.store.cleanup()
        self.assertEqual(self.business.store.task(created['task_ids'][0])['status'], 'PREPROCESSING')
        impact = self.client.get('/api/v1/admin/retention').json()['impact']
        self.assertTrue(all(i['eligible_count']==0 and i['active_count']==1 for i in impact))
        self.business.store.finish_stopped(active, 'EXTRACT_TIMEOUT')
        self.business.store.cleanup()
        self.assertEqual(self.business.store.tasks(), [])

    def test_overdue_queued_rerun_survives_policy_change_and_startup_until_stopped(self):
        self.admin()
        for outcome in ('cancelled', 'failed', 'completed'):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.save(None).status_code, 200)
                created = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
                with patch('ocr_app.task_store.now', return_value=created):
                    task = self.ready(values=dict(name='synthetic'))
                result = self.business.store.result(task['task_id'])
                response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/rerun', headers=self.headers,
                    json=dict(run_id=task['run_id'], expected_revision=task['result_revision']))
                self.assertEqual(response.status_code, 202)
                queued = response.json()
                with self.business.engine.connect() as connection:
                    history = {table: connection.execute(text('SELECT * FROM ' + table)).all()
                               for table in ('runs', 'artifacts', 'attempts')}
                blobs = {p.name: p.read_bytes() for p in self.business.storage.blobs.iterdir()}
                response = self.save(7)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['impact'][0], dict(days=7, eligible_count=0, active_count=1))
                self.business.prepare()
                current = self.business.store.task(task['task_id'])
                self.assertEqual(current['status'], 'QUEUED')
                self.assertEqual(current['run_id'], queued['run_id'])
                self.assertEqual(current['expires_at'], (datetime.fromisoformat(created) + timedelta(days=7)).isoformat())
                with self.business.engine.connect() as connection:
                    self.assertEqual(history, {table: connection.execute(text('SELECT * FROM ' + table)).all()
                                             for table in history})
                self.assertEqual(blobs, {p.name: p.read_bytes() for p in self.business.storage.blobs.iterdir()})
                if outcome == 'cancelled':
                    self.business.store.cancel(current['task_id'], current['run_id'], current['result_revision'], 'test')
                else:
                    claimed = self.business.store.claim_next()
                    self.assertEqual(claimed['id'], current['task_id'])
                    if outcome == 'failed':
                        self.business.store.finish_stopped(claimed, 'EXTRACT_TIMEOUT')
                    else:
                        result['status'] = 'COMPLETED'
                        self.assertTrue(self.business.store.publish(claimed, result))
                self.business.store.cleanup()
                self.assertEqual(self.business.store.tasks(), [])
                self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_roles_csrf_validation_and_confirmation(self):
        self.assertEqual(self.client.get('/api/v1/admin/retention').status_code, 401)
        for role in ('operator','viewer'):
            self.admin(role)
            self.assertEqual(self.client.get('/api/v1/admin/retention').status_code, 403)
            self.assertEqual(self.save(None).status_code, 403)
        self.admin()
        valid = dict(days=15, expected_revision=0, confirmed=True)
        for change in ({'days':0}, {'days':True}, {'days':'15'}, {'days':15.0}, {'days':[]},
                       {'confirmed':False}, {'confirmed':1}, {'expected_revision':True}, {'extra':1}):
            response = self.client.put('/api/v1/admin/retention', headers=self.headers, json=dict(valid, **change))
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.put('/api/v1/admin/retention', headers=self.headers,
            json=dict(days=15,expected_revision=0)).status_code, 422)
        self.assertEqual(self.client.put('/api/v1/admin/retention', headers=self.origin, json=valid).status_code, 403)
        self.assertEqual(self.client.put('/api/v1/admin/retention', headers=dict(self.headers,Origin='https://foreign.invalid'),json=valid).status_code,403)
        self.assertEqual(self.policy(), dict(days=7,revision=0))

    def test_stale_and_concurrent_admin_saves_do_not_overwrite(self):
        self.admin()
        store=self.business.store
        def update(days):
            try:
                return save_configuration(store, dict(days=days, expected_revision=0, confirmed=True), 'synthetic', authorize=lambda c: None)['days']
            except TaskError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(update,[15,30]))
        self.assertEqual(results.count('RETENTION_VERSION_CONFLICT'),1)
        self.assertEqual(self.policy()['revision'],1)
        response=self.save(None,revision=0)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['code'],'RETENTION_VERSION_CONFLICT')

    def test_authorization_rechecked_inside_write_even_noop(self):
        self.admin()
        original=self.business.accounts._acting_user
        def revoke(connection, actor, token, **kwargs):
            connection.execute(text('DELETE FROM web_sessions'))
            return original(connection, actor, token, **kwargs)
        before=self.policy()
        with patch.object(self.business.accounts,'_acting_user',side_effect=revoke):
            self.assertEqual(self.save(7).status_code,401)
        self.assertEqual(self.policy(),before)

    def test_failure_rolls_back_policy_and_deadlines_together(self):
        self.admin()
        task=self.ready()
        before=self.snapshot(task['task_id'])
        with patch.object(self.business.store,'_audit',side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaises(RuntimeError):
                save_configuration(self.business.store, dict(days=30,expected_revision=0,confirmed=True),'test',authorize=lambda c:None)
        self.assertEqual(self.policy(),dict(days=7,revision=0))
        self.assertEqual(self.snapshot(task['task_id']),before)

    def test_append_uses_own_upload_clock_and_never_still_allows_manual_delete(self):
        self.admin()
        file=dict(data=self.image,name='synthetic.png',mime='image/png')
        with patch('ocr_app.task_store.now',return_value='2026-01-01T00:00:00+00:00'):
            package=self.business.store.create_batch([file],'DIPLOMA','test',person_name='synthetic')
        self.save(30)
        with patch('ocr_app.task_store.now',return_value='2026-01-10T00:00:00+00:00'):
            self.business.store.append_batch(package['batch_id'],[dict(file,data=b'other')],'DIPLOMA',0,'test',user=None,authorize=lambda c:None)
        self.assertEqual([t['expires_at'] for t in self.business.store.tasks(package['batch_id'])],
                         ['2026-01-31T00:00:00+00:00','2026-02-09T00:00:00+00:00'])
        self.save(None)
        versions=[]
        for task in self.business.store.tasks(package['batch_id']):
            self.business.store.cancel(task['task_id'],task['run_id'],task['result_revision'],'test')
            current=self.business.store.task(task['task_id'])
            versions.append(dict(task_id=current['task_id'],run_id=current['run_id'],expected_revision=current['result_revision']))
        self.business.store.delete_batch(package['batch_id'],versions,'test',authorize=lambda c:None)
        self.assertEqual(self.business.store.tasks(),[])


if __name__=='__main__':
    unittest.main()
