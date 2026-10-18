"""Isolated contention, staging and admission checks; no live data or OCR models."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import text

import test_review_api as review
from ocr_app.admission import Admission
from ocr_app.db import write_transaction
from ocr_app.task_errors import TaskError


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_overflow_account_limit_and_cancel_cleanup(self):
        gate = Admission(active=1, waiting=2, timeout=2, per_account=1)
        order = []

        async def enter(name):
            async with gate.enter(name):
                order.append(name)
                await asyncio.sleep(0)

        async with gate.enter('first'):
            one = asyncio.create_task(enter('one'))
            await asyncio.sleep(0)
            two = asyncio.create_task(enter('two'))
            await asyncio.sleep(0)
            with self.assertRaises(TaskError) as duplicate:
                async with gate.enter('one'):
                    self.fail('duplicate admitted')
            self.assertEqual(duplicate.exception.status, 429)
            with self.assertRaises(TaskError) as full:
                async with gate.enter('three'):
                    self.fail('overflow admitted')
            self.assertEqual(full.exception.status, 503)
            one.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await one
            three = asyncio.create_task(enter('three'))
            await asyncio.sleep(0)
        await asyncio.gather(two, three)
        self.assertEqual(order, ['two', 'three'])
        self.assertEqual((gate.active, len(gate.waiters), gate.accounts), (0, 0, {}))

    async def test_timeout_and_cancel_after_slot_grant_do_not_leak(self):
        gate = Admission(active=1, timeout=.01)
        async with gate.enter('held'):
            with self.assertRaises(TaskError) as timeout:
                async with gate.enter('timeout'):
                    self.fail('timeout admitted')
            self.assertEqual(timeout.exception.code, 'SERVICE_BUSY')
        gate.timeout = 2
        held = gate.enter('held')
        await held.__aenter__()
        async def waiting():
            async with gate.enter('cancelled'):
                await asyncio.sleep(10)
        task = asyncio.create_task(waiting())
        await asyncio.sleep(0)
        await held.__aexit__(None, None, None)  # Grant, then cancel before resumption.
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((gate.active, len(gate.waiters), gate.accounts), (0, 0, {}))


class PersistenceTests(unittest.TestCase):
    setUp = review.ReviewAPITests.setUp
    upload = review.ReviewAPITests.upload
    task = review.ReviewAPITests.task
    ready = review.ReviewAPITests.ready
    submit = review.ReviewAPITests.submit

    def assert_files_referenced(self):
        with self.business.engine.connect() as c:
            references = set(c.execute(text('SELECT reference FROM artifacts WHERE reference IS NOT NULL')).scalars())
        self.assertEqual({p.stem for p in self.business.storage.blobs.glob('*.bin')}, references)
        for reference in references:
            self.business.storage.read(reference)

    def while_put_assert_other_writer_can_commit(self):
        original = self.business.storage.put
        def put(data):
            # A distinct SQLite connection stands in for another writer process.
            with closing(sqlite3.connect(self.business.root / 'tasks.sqlite3', timeout=.05)) as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute('UPDATE retention_settings SET revision=revision WHERE id=1')
                c.commit()
            return original(data)
        return patch.object(self.business.storage, 'put', side_effect=put)

    def test_upload_review_export_fsync_do_not_own_sqlite_writer(self):
        with self.while_put_assert_other_writer_can_commit():
            task, _ = self.ready()
            response = self.submit(task, fields=review.CERT)
            self.assertEqual(response.status_code, 200, response.text)
            response = self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [task['task_id']]})
            self.assertEqual(response.status_code, 200, response.text[:80] if response.status_code != 200 else '')
        self.assert_files_referenced()

    def test_upload_rejected_after_staging_leaves_no_batch_or_file(self):
        count = 0
        def authorize(connection):
            nonlocal count
            count += 1
            if count == 2:
                raise TaskError('UNAUTHORIZED', 'synthetic', 401)
        with self.assertRaises(TaskError):
            self.business.store.create_batch([dict(data=self.image, name='synthetic.png', mime='image/png',
                actual_source_page_count=1)], 'DIPLOMA', self.business.accounts.accounts[0]['user_id'], authorize=authorize)
        self.assertEqual(self.business.store.batches()['total'], 0)
        self.assert_files_referenced()

    def test_duplicate_staged_uploads_are_cleaned_after_success(self):
        owner = self.business.accounts.accounts[0]['user_id']
        file = dict(data=self.image, name='synthetic.png', mime='image/png', actual_source_page_count=1)
        result = self.business.store.create_batch([file, file], 'DIPLOMA', owner)
        self.assertEqual(len(result['task_ids']), 1)
        self.assert_files_referenced()

    def test_review_conflict_after_staging_preserves_other_revision_and_cleans_file(self):
        task, _ = self.ready()
        original = self.business.storage.put
        def change_version(data):
            reference = original(data)
            with self.business.store.transaction() as c:
                c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), {'id': task['task_id']})
            return reference
        with patch.object(self.business.storage, 'put', side_effect=change_version):
            response = self.submit(task, fields=review.CERT)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'RESULT_VERSION_CONFLICT')
        self.assertEqual(self.task(task['task_id'])['result_revision'], task['result_revision'] + 1)
        self.assert_files_referenced()

    def test_export_detects_changes_during_generation_and_never_records_success(self):
        from ocr_app.exporting import workbook_bytes
        task, _ = self.ready()
        task = self.submit(task, fields=review.CERT).json()
        for change in ['task', 'policy', 'batch']:
            def mutate(*args, **kwargs):
                data = workbook_bytes(*args, **kwargs)
                with self.business.store.transaction() as c:
                    if change == 'task':
                        c.execute(text('UPDATE tasks SET revision=revision+1 WHERE id=:id'), {'id': task['task_id']})
                    elif change == 'policy':
                        c.execute(text('UPDATE required_field_settings SET revision=revision+1 WHERE id=1'))
                    else:
                        c.execute(text('UPDATE batches SET package_revision=package_revision+1 WHERE id=:id'), {'id': task['batch_id']})
                return data
            # Ensure the policy row exists before testing policy revision conflicts.
            if change == 'policy':
                with self.business.store.transaction() as c:
                    c.execute(text("INSERT OR IGNORE INTO required_field_settings(id,revision,overrides_json) VALUES(1,0,'{}')"))
            with patch('ocr_app.exporting.workbook_bytes', side_effect=mutate):
                response = self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [task['task_id']]})
            self.assertEqual(response.status_code, 409, response.text)
            self.assert_files_referenced()
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT COUNT(*) FROM audit WHERE event='export_generated'")).scalar_one(), 0)

    def test_committed_review_history_survives_a_later_response_read_failure(self):
        task, _ = self.ready()
        with patch.object(self.business.store, 'task', side_effect=OSError('synthetic response read failure')):
            response = self.submit(task, fields=review.CERT)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.task(task['task_id'])['result_revision'], task['result_revision'] + 1)
        with self.business.engine.connect() as c:
            references = c.execute(text("SELECT reference FROM artifacts WHERE task_id=:id AND kind='review_revision'"), {'id': task['task_id']}).scalars().all()
        self.assertEqual(len(references), 1)
        fields = json.loads(self.business.storage.read(references[0]))['after']['fields']
        self.assertEqual(next(field['value'] for field in fields if field['key'] == 'name'), review.CERT['name'])
        self.assert_files_referenced()

    def test_failed_export_final_commit_cleans_all_staged_histories(self):
        task, _ = self.ready()
        self.submit(task, fields=review.CERT)
        original = self.business.store._audit
        def fail(connection, event, *args, **kwargs):
            if event == 'export_generated':
                raise OSError('synthetic commit failure')
            return original(connection, event, *args, **kwargs)
        with patch.object(self.business.store, '_audit', side_effect=fail):
            response = self.client.post('/api/v1/export', headers=self.headers, json={'task_ids': [task['task_id']]})
        self.assertEqual(response.status_code, 500)
        self.assert_files_referenced()

    def test_another_process_lock_becomes_bounded_busy_without_replaying_body(self):
        task = self.task(self.upload().json()['task_ids'][0])
        code = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); print('ready',flush=True); sys.stdin.readline(); c.rollback()"
        child = subprocess.Popen([sys.executable, '-c', code, str(self.business.root / 'tasks.sqlite3')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with self.business.engine.connect() as c:
                c.exec_driver_sql('PRAGMA busy_timeout=30')
            with self.assertRaises(TaskError) as busy:
                with write_transaction(self.business.engine):
                    self.fail('busy transaction body must never run')
            self.assertEqual((busy.exception.code, busy.exception.status), ('SERVICE_BUSY', 503))
            response = self.client.post('/api/v1/tasks/' + task['task_id'] + '/cancel', headers=self.headers,
                json=dict(run_id=task['run_id'], expected_revision=task['result_revision']))
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()['code'], 'SERVICE_BUSY')
            self.assertEqual(response.headers['Retry-After'], '2')
            self.assertEqual(self.task(task['task_id'])['status'], 'QUEUED')
        finally:
            child.communicate('\n', timeout=5)
        with write_transaction(self.business.engine) as c:
            c.exec_driver_sql('PRAGMA busy_timeout=5000')

    def test_http_full_queue_rejects_before_reading_multipart_and_without_audit_writes(self):
        async def check():
            gate = self.client.app.state.upload_admission = Admission(active=1, waiting=0)
            consumed = False
            async def body():
                nonlocal consumed
                consumed = True
                yield b'never consume this body'
            async with gate.enter('other'):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.client.app), base_url='http://127.0.0.1') as client:
                    response = await client.post('/api/v1/batches', headers=self.headers, content=body())
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.headers['Retry-After'], '2')
            self.assertNotIn('X-Queue-Wait-Ms', response.headers)
            self.assertFalse(consumed)
        with self.business.engine.connect() as c:
            before = c.execute(text('SELECT COUNT(*) FROM audit')).scalar_one()
        asyncio.run(check())
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT COUNT(*) FROM audit')).scalar_one(), before)

    def test_worker_process_publication_with_upload_review_and_export(self):
        from ocr_app.extraction import extract_result
        from ocr_app.exporting import export_results
        owner = self.business.accounts.accounts[0]['user_id']
        saved, _ = self.ready()
        saved = self.submit(saved, fields=review.CERT).json()
        export_task, _ = self.ready()
        self.submit(export_task, fields=review.CERT)
        worker_id = self.upload().json()['task_ids'][0]
        worker = self.business.store.claim_next()
        self.assertEqual(worker['id'], worker_id)
        result = extract_result([], 'DIPLOMA')
        result['status'] = 'NEED_REVIEW'
        code = '''
import json,sys,time
from pathlib import Path
from ocr_app.db import open_database
from ocr_app.storage import Storage
from ocr_app.task_store import TaskStore
data=json.loads(sys.stdin.readline()); root=Path(sys.argv[1])
store=TaskStore(open_database(root,migrate=False),Storage(root,key=b'T'*32))
print('ready',flush=True);sys.stdin.readline()
try:
 for index in range(20):
  assert store.progress(data['task'],'OCR',index)
  store.attempt(data['task'],{'index':index,'synthetic':True})
  time.sleep(.005)
 assert store.publish(data['task'],data['result'])
 print('published',flush=True)
finally: store.engine.dispose()
'''
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'backend'))
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.business.root)],
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            child.stdin.write(json.dumps(dict(task={key: worker[key] for key in ['id', 'run_id', 'revision']}, result=result)) + '\n'); child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            def upload(index):
                return self.business.store.create_batch([dict(data=self.image, name='synthetic.png', mime='image/png', actual_source_page_count=1)], 'DIPLOMA', owner)
            def save():
                return self.business.store.review(saved['task_id'], dict(run_id=saved['run_id'], expected_revision=saved['result_revision'], fields=dict(review.CERT, name='合成并发修正')), owner)
            with ThreadPoolExecutor(max_workers=8) as pool:
                jobs = [pool.submit(upload, i) for i in range(12)]
                jobs.append(pool.submit(save))
                # A distinct complete task avoids intentionally exporting a changing version.
                jobs.append(pool.submit(export_results, self.business.store, {'task_ids': [export_task['task_id']]}, owner, 'operator'))
                child.stdin.write('\n'); child.stdin.flush()
                for job in jobs:
                    job.result(timeout=20)
            stdout, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn('published', stdout)
        finally:
            if child.poll() is None:
                child.kill(); child.communicate(timeout=5)
        self.assertEqual(self.task(worker_id)['status'], 'NEED_REVIEW')
        self.assertEqual(self.task(saved['task_id'])['result_revision'], saved['result_revision'] + 1)
        self.assert_files_referenced()

    def test_revoked_session_cannot_upload_after_queue_wait(self):
        self.business.accounts.set_user('queued', 'synthetic-password', '合成账号')
        login = self.client.post('/api/v1/auth/login', headers={'Origin': 'http://127.0.0.1'},
            json={'username': 'queued', 'password': 'synthetic-password'})
        token = self.client.cookies.get('ocr_session')
        headers = {'Origin': 'http://127.0.0.1', 'X-CSRF-Token': login.json()['csrf_token'], 'Cookie': 'ocr_session=' + token}
        async def check():
            gate = self.client.app.state.upload_admission = Admission(active=1)
            held = gate.enter('other')
            await held.__aenter__()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.client.app), base_url='http://127.0.0.1') as client:
                task = asyncio.create_task(client.post('/api/v1/batches', headers=headers, content=b'invalid'))
                for _ in range(100):
                    if gate.waiters:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(len(gate.waiters), 1)
                self.business.accounts.logout(token)
                await held.__aexit__(None, None, None)
                response = await task
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(gate.active, 0)
        asyncio.run(check())


if __name__ == '__main__':
    unittest.main()
