"""Permanent batch deletion uses isolated SQLite and synthetic documents only."""
import concurrent.futures
import threading
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import event, text
import test_business_api as base
from ocr_app.task_store import TaskError


class BatchDeletionTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp

    def admin(self, role='admin'):
        user = self.business.accounts.set_user('synthetic-' + role, 'synthetic password 2026', '合成账号', role)
        response = self.client.post('/api/v1/auth/login', headers={'Origin': 'http://127.0.0.1'},
                                    json=dict(username='synthetic-' + role, password='synthetic password 2026'))
        self.assertEqual(response.status_code, 200, response.text)
        self.token = self.client.cookies.get('ocr_session')
        self.user = user
        return {'Origin': 'http://127.0.0.1', 'X-CSRF-Token': response.json()['csrf_token']}

    def create(self, statuses=('NEED_REVIEW',), data=b'synthetic original'):
        created = self.business.store.create_batch([
            dict(data=data + str(i).encode(), name='private-synthetic.png', mime='image/png')
            for i in range(len(statuses))], 'DIPLOMA', 'synthetic-actor')
        with self.business.store.transaction() as c:
            for identifier, status in zip(created['task_ids'], statuses):
                c.execute(text('UPDATE tasks SET status=:status WHERE id=:id'), dict(id=identifier, status=status))
        return created['batch_id']

    def versions(self, batch):
        return [dict(task_id=t['task_id'], run_id=t['run_id'], expected_revision=t['result_revision'])
                for t in self.business.store.tasks(batch)]

    def delete(self, batch, headers, versions=None):
        return self.client.request('DELETE', '/api/v1/batches/' + batch, headers=headers,
                                   json=dict(versions=self.versions(batch) if versions is None else versions))

    def direct(self, batch, versions):
        return self.business.store.delete_batch(batch, versions, self.user['user_id'],
            authorize=lambda c: self.business.accounts._acting_user(c, self.user['user_id'], self.token, administrator=True))

    def test_permissions_origin_csrf_and_missing_batch(self):
        batch = self.create()
        versions = self.versions(batch)
        self.assertEqual(self.delete(batch, {}, versions).status_code, 401)
        for role in ('viewer', 'operator'):
            self.assertEqual(self.delete(batch, self.admin(role), versions).status_code, 403)
        headers = self.admin()
        self.assertEqual(self.delete(batch, {'Origin': 'http://127.0.0.1'}, versions).status_code, 403)
        self.assertEqual(self.delete(batch, dict(headers, Origin='http://wrong.invalid'), versions).status_code, 403)
        self.assertEqual(self.delete(str(uuid.uuid4()), headers, versions).status_code, 404)
        self.assertEqual(len(self.business.store.tasks(batch)), 1)

    def test_all_stopped_states_and_duplicate_request(self):
        batch = self.create(('NEED_REVIEW', 'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'))
        versions = self.versions(batch)
        headers = self.admin()
        result = self.delete(batch, headers, versions)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(set(result.json()['task_ids']), {v['task_id'] for v in versions})
        self.assertFalse(result.json()['cleanup_pending'])
        self.assertEqual(self.delete(batch, headers, versions).status_code, 404)
        self.assertEqual(self.business.store.batches()['total'], 0)
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])
        with self.business.engine.connect() as c:
            audit = c.execute(text("SELECT * FROM audit WHERE event IN ('task_deleted','batch_deleted')")).mappings().all()
        self.assertEqual(len(audit), 6)
        self.assertNotIn('private-synthetic', str(audit))

    def test_one_running_or_queued_task_blocks_entire_batch(self):
        headers = self.admin()
        for state in ('QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'):
            with self.subTest(state=state):
                batch = self.create(('COMPLETED', state))
                blobs = set(self.business.storage.blobs.iterdir())
                response = self.delete(batch, headers)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()['code'], 'INVALID_STATE')
                self.assertEqual(len(self.business.store.tasks(batch)), 2)
                self.assertEqual(set(self.business.storage.blobs.iterdir()), blobs)

    def test_exact_membership_and_versions_are_required(self):
        headers = self.admin()
        batch = self.create(('COMPLETED', 'NEED_REVIEW'))
        versions = self.versions(batch)
        invalid = [[], [versions[0], versions[0]], [dict(versions[0], expected_revision=-1)],
                   [dict(versions[0], expected_revision=True)], [dict(versions[0], extra='x')]]
        for values in invalid:
            self.assertEqual(self.delete(batch, headers, values).status_code, 422)
        stale = [versions[:1], [dict(versions[0], task_id=str(uuid.uuid4())), versions[1]],
                 [dict(versions[0], run_id=str(uuid.uuid4())), versions[1]],
                 [dict(versions[0], expected_revision=99), versions[1]]]
        for values in stale:
            response = self.delete(batch, headers, values)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['code'], 'RESULT_VERSION_CONFLICT')
        self.assertEqual(len(self.business.store.tasks(batch)), 2)

    def test_all_run_history_removed_but_identical_other_batch_kept(self):
        headers = self.admin()
        store = self.business.store
        batch = self.create(('QUEUED',))
        other = self.create(('NEED_REVIEW',))
        other_task = store.tasks(other)[0]
        other_refs = set(self.business.storage.blobs.iterdir())
        for i in range(2):
            task = store.claim_next()
            store.save_page(task, 1, b'synthetic corrected page', 10, 10)
            store.attempt(task, {'text': 'synthetic OCR history'})
            store.publish(task, dict(doc_type='DIPLOMA', status='NEED_REVIEW', fields=[], pages=[], raw_text='synthetic', review_issues=[], warnings=[]))
            with store.transaction() as c:
                row = store._row(c, task['id'])
                store._access_history(c, row, 'synthetic-actor', 'export_full', 'synthetic access')
            if i == 0:
                current = store.task(task['id'])
                store.rerun(task['id'], current['run_id'], current['result_revision'], 'synthetic-actor')
        response = self.delete(batch, headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(store.task(other_task['task_id']), other_task)
        self.assertEqual(len(list(self.business.storage.blobs.iterdir())), 1)
        with self.business.engine.connect() as c:
            for table in ('runs', 'artifacts', 'attempts'):
                self.assertEqual(c.execute(text(f'SELECT count(*) FROM {table} WHERE task_id=:id'), {'id': task['id']}).scalar(), 0)
        self.assertTrue(other_refs.intersection(self.business.storage.blobs.iterdir()))

    def test_sql_failure_rolls_back_without_unlinking(self):
        self.admin()
        batch = self.create()
        versions = self.versions(batch)
        files = {p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}
        def fail(c, cursor, statement, parameters, context, many):
            if statement.startswith('DELETE FROM batches'):
                raise RuntimeError('synthetic commit failure')
        event.listen(self.business.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaises(RuntimeError):
                self.direct(batch, versions)
        finally:
            event.remove(self.business.engine, 'before_cursor_execute', fail)
        self.assertEqual(self.versions(batch), versions)
        self.assertEqual({p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}, files)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM audit WHERE event='batch_deleted'")).scalar(), 0)

    def test_unlink_failure_is_reported_and_orphan_cleanup_can_finish(self):
        headers = self.admin()
        batch = self.create()
        with patch.object(self.business.storage, 'delete', side_effect=PermissionError('synthetic locked file')):
            response = self.delete(batch, headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['cleanup_pending'])
        self.assertEqual(self.business.store.batches()['total'], 0)
        self.assertEqual(len(list(self.business.storage.blobs.iterdir())), 1)
        self.business.store.cleanup_orphans()
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_revoked_session_cannot_commit_after_route_check(self):
        headers = self.admin()
        batch = self.create()
        original = self.business.store.delete_batch
        def revoked(*args, **kwargs):
            self.business.accounts.logout(self.token)
            return original(*args, **kwargs)
        with patch.object(self.business.store, 'delete_batch', side_effect=revoked):
            response = self.delete(batch, headers)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(len(self.business.store.tasks(batch)), 1)

    def test_concurrent_rerun_or_review_never_partially_deletes(self):
        self.admin()
        for operation in ('rerun', 'review'):
            batch = self.create()
            versions = self.versions(batch)
            task = versions[0]
            barrier = threading.Barrier(2)
            def run(action):
                barrier.wait()
                try:
                    if action == 'delete':
                        self.direct(batch, versions)
                    elif action == 'rerun':
                        self.business.store.rerun(task['task_id'], task['run_id'], task['expected_revision'], 'synthetic')
                    else:
                        with self.business.store.transaction() as c:
                            row = self.business.store._row(c, task['task_id'])
                            self.business.store._expected(row, task['run_id'], task['expected_revision'])
                            c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), {'id': task['task_id']})
                    return 'ok'
                except TaskError as error:
                    return error.status
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                deletion = pool.submit(run, 'delete')
                mutation = pool.submit(run, operation)
                results = [deletion.result(), mutation.result()]
            self.assertEqual(results.count('ok'), 1, results)
            if results[0] == 'ok':
                self.assertEqual(results[1], 404)
            else:
                self.assertEqual(results[0], 409)
                self.assertEqual(len(self.business.store.tasks(batch)), 1)
