"""Duplicate snapshots are not additional durable progress or heartbeats."""
import copy
import unittest
from sqlalchemy import event, text
import test_task_store as existing


class ProgressWriteCostTests(unittest.TestCase):
    setUp = existing.TaskStoreTests.setUp
    create = existing.TaskStoreTests.create

    def test_identical_snapshots_skip_updates_but_page_and_stage_changes_persist(self):
        self.create()
        task = self.store.claim_next()
        pages = [dict(page_index=1, regions=[dict(status='pending')])]
        updates = []
        def executed(connection, cursor, statement, parameters, context, many):
            if statement.startswith('UPDATE tasks SET status=:') or statement.startswith('UPDATE tasks SET status='):
                updates.append(statement)
        event.listen(self.engine, 'after_cursor_execute', executed)
        self.addCleanup(event.remove, self.engine, 'after_cursor_execute', executed)
        for _ in range(6):
            self.assertTrue(self.store.progress(task, 'OCR', 25, copy.deepcopy(pages)))
        self.assertEqual(len(updates), 1)
        pages[0]['regions'][0]['status'] = 'recognized'
        self.assertTrue(self.store.progress(task, 'OCR', 25, pages))
        self.assertTrue(self.store.progress(task, 'EXTRACTING', 25, pages))
        self.assertEqual(len(updates), 3)
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id':task['id']}).mappings().one()
            self.assertEqual(self.storage.unpack(row['pages_enc']), pages)
            self.assertEqual(row['status'], 'EXTRACTING')

    def test_identical_snapshot_does_not_bypass_cancel_or_stale_run(self):
        self.create()
        task = self.store.claim_next()
        self.assertTrue(self.store.progress(task, 'OCR', 0, []))
        with self.store.transaction() as connection:
            connection.execute(text('UPDATE tasks SET cancel_requested=1 WHERE id=:id'), {'id':task['id']})
        self.assertFalse(self.store.progress(task, 'OCR', 0, []))
        with self.store.transaction() as connection:
            connection.execute(text('UPDATE tasks SET cancel_requested=0,run_id=:run WHERE id=:id'), {'id':task['id'],'run':'new-run'})
        self.assertFalse(self.store.progress(task, 'OCR', 0, []))
