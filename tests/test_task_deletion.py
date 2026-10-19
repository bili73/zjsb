"""Individual deletion uses synthetic task-owned data and live session checks."""
import concurrent.futures
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import event, text

import test_batch_ownership as ownership
from ocr_app.task_errors import TaskError


class TaskDeletionTests(unittest.TestCase):
    setUp = ownership.BatchOwnershipTests.setUp
    account = ownership.BatchOwnershipTests.account
    batch = ownership.BatchOwnershipTests.batch
    password = ownership.BatchOwnershipTests.password

    def delete(self, task, headers, **version):
        return self.client.request('DELETE', '/api/v1/tasks/' + task['task_id'], headers=headers,
            json=dict(run_id=task['run_id'], expected_revision=task['result_revision'], **version))

    def test_owner_can_delete_one_without_touching_active_peer_and_last_removes_batch(self):
        user, headers, _ = self.account('owner')
        created = self.business.store.create_batch([
            dict(data=self.image + str(i).encode(), name=f'synthetic-{i}.png', mime='image/png')
            for i in range(2)], 'DIPLOMA', user['user_id'])
        first, second = self.business.store.tasks(created['batch_id'])
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE tasks SET status='NEED_REVIEW' WHERE id=:id"), {'id': first['task_id']})
            c.execute(text("UPDATE tasks SET status='OCR' WHERE id=:id"), {'id': second['task_id']})
        peer = self.business.store.task(second['task_id'])
        response = self.delete(first, headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['batch_deleted'])
        self.assertEqual(self.business.store.task(second['task_id']), peer)
        batch = self.business.store.batch(created['batch_id'])
        self.assertEqual((batch['task_count'], batch['package_revision']), (1, 1))
        self.assertEqual(self.delete(second, headers).status_code, 409)
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE tasks SET status='CANCELLED' WHERE id=:id"), {'id': second['task_id']})
        response = self.delete(second, headers)
        self.assertTrue(response.json()['batch_deleted'], response.text)
        self.assertEqual(self.business.store.batches(user=user)['total'], 0)
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_authorization_origin_csrf_foreign_owner_and_viewer(self):
        user, headers, _ = self.account('alice')
        _, task = self.batch(user)
        _, foreign, _ = self.account('bob')
        _, viewer, _ = self.account('reader', 'viewer')
        for supplied, status in [({}, 401), (foreign, 404), (viewer, 403),
                ({'Cookie': headers['Cookie'], 'Origin': headers['Origin']}, 403),
                (dict(headers, Origin='http://foreign.invalid'), 403)]:
            self.assertEqual(self.delete(task, supplied).status_code, status)
            self.assertEqual(self.business.store.task(task['task_id'])['result_revision'], task['result_revision'])
        _, admin, _ = self.account('administrator', 'admin')
        self.assertEqual(self.delete(task, admin).status_code, 200)
        self.assertEqual(self.delete(task, admin).status_code, 404)

    def test_all_stopped_states_and_versions(self):
        user, headers, _ = self.account('owner')
        for status in ('NEED_REVIEW', 'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'):
            with self.subTest(status=status):
                _, task = self.batch(user, status)
                self.assertEqual(self.delete(task, headers).status_code, 200)
        for status in ('QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'):
            _, task = self.batch(user, status)
            self.assertEqual(self.delete(task, headers).status_code, 409)
        _, task = self.batch(user)
        with self.business.store.transaction() as c:
            c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), {'id': task['task_id']})
        response = self.delete(task, headers)
        self.assertEqual((response.status_code, response.json()['code']), (409, 'RESULT_VERSION_CONFLICT'))

    def test_revocation_between_route_check_and_transaction_blocks_deletion(self):
        user, headers, token = self.account('owner')
        _, task = self.batch(user)
        original = self.business.store.delete_task
        def revoke(*args, **kwargs):
            self.business.accounts.logout(token)
            return original(*args, **kwargs)
        with patch.object(self.business.store, 'delete_task', side_effect=revoke):
            self.assertEqual(self.delete(task, headers).status_code, 401)
        self.assertEqual(self.business.store.task(task['task_id'])['task_id'], task['task_id'])

    def test_rollback_preserves_files_and_no_success_audit(self):
        user, headers, _ = self.account('owner')
        batch, task = self.batch(user)
        files = {p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}
        def fail(c, cursor, statement, parameters, context, many):
            if statement.startswith('DELETE FROM batches'):
                raise RuntimeError('synthetic rollback')
        event.listen(self.business.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaises(RuntimeError):
                self.business.store.delete_task(task['task_id'], task['run_id'], task['result_revision'], user['user_id'],
                    user=user, authorize=lambda c: None)
        finally:
            event.remove(self.business.engine, 'before_cursor_execute', fail)
        self.assertEqual(self.business.store.batch(batch)['task_count'], 1)
        self.assertEqual({p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}, files)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM audit WHERE event='task_deleted'")).scalar(), 0)

    def test_unlink_failure_returns_pending_and_audit_survives_last_task(self):
        user, headers, _ = self.account('owner')
        batch, task = self.batch(user)
        with patch.object(self.business.storage, 'delete', side_effect=PermissionError('synthetic file lock')):
            response = self.delete(task, headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['cleanup_pending'])
        with self.business.engine.connect() as c:
            row = c.execute(text("SELECT * FROM audit WHERE event='task_deleted' AND outcome='success'")).mappings().one()
            self.assertEqual((row['actor'], row['task_id'], row['batch_id']), (user['user_id'], task['task_id'], batch))
            for table in ('runs', 'attempts', 'artifacts'):
                self.assertEqual(c.execute(text(f'SELECT count(*) FROM {table} WHERE task_id=:id'), {'id': task['task_id']}).scalar(), 0)
        self.business.store.cleanup_orphans()
        self.assertEqual(list(self.business.storage.blobs.iterdir()), [])

    def test_deletes_every_run_artifact_but_preserves_other_batch(self):
        user, headers, _ = self.account('owner')
        _, peer = self.batch(user)
        peer_files = {p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}
        store = self.business.store
        created = store.create_batch([dict(data=b'synthetic source', name='synthetic.png', mime='image/png')],
                                     'DIPLOMA', user['user_id'])
        for index in range(2):
            running = store.claim_next()
            store.save_page(running, 1, b'synthetic corrected page', 10, 10)
            store.attempt(running, {'text': 'synthetic old OCR'})
            store.publish(running, dict(doc_type='DIPLOMA', status='NEED_REVIEW', fields=[], pages=[],
                                       raw_text='synthetic OCR', review_issues=[], warnings=[]))
            with store.transaction() as c:
                store._access_history(c, store._row(c, running['id']), user['user_id'], 'export_full', 'synthetic export')
            current = store.task(running['id'])
            if index == 0:
                store.rerun(running['id'], current['run_id'], current['result_revision'], user['user_id'])
        response = self.delete(current, headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(store.task(peer['task_id']), peer)
        self.assertEqual({p: p.read_bytes() for p in self.business.storage.blobs.iterdir()}, peer_files)
        with self.business.engine.connect() as c:
            for table in ('runs', 'artifacts', 'attempts'):
                self.assertEqual(c.execute(text(f'SELECT count(*) FROM {table} WHERE task_id=:id'),
                    {'id': created['task_ids'][0]}).scalar(), 0)

    def test_concurrent_save_or_rerun_has_one_winner_and_never_deletes_a_new_version(self):
        user, _, _ = self.account('owner')
        for operation in ('review', 'rerun'):
            _, task = self.batch(user)
            barrier = threading.Barrier(2)
            def execute(action):
                barrier.wait(timeout=8)
                try:
                    store = self.business.store
                    if action == 'delete':
                        store.delete_task(task['task_id'], task['run_id'], task['result_revision'],
                                          user['user_id'], user=user, authorize=lambda c: None)
                    elif operation == 'rerun':
                        store.rerun(task['task_id'], task['run_id'], task['result_revision'], user['user_id'])
                    else:
                        with store.transaction() as c:
                            row = store._row(c, task['task_id'], user=user)
                            store._expected(row, task['run_id'], task['result_revision'])
                            c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), {'id': task['task_id']})
                    return 'ok'
                except TaskError as error:
                    return error.status
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(execute, ('delete', 'mutate')))
            self.assertEqual(results.count('ok'), 1, results)
            self.assertIn(next(item for item in results if item != 'ok'), (404, 409))


if __name__ == '__main__':
    unittest.main()
