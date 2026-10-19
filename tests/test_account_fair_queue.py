"""Account fairness uses temporary SQLite/encrypted synthetic files, never models."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.db import open_database
from ocr_app.storage import Storage
from ocr_app.task_store import TaskStore


CERTIFICATES = {'DIPLOMA', 'DEGREE_CERT'}
PADDLE = {'MEDICAL_REPORT', 'GENERIC'}


class AccountFairQueueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'data'
        self.storage = Storage(self.root, key=b'Q' * 32)
        self.engine = open_database(self.root)
        self.addCleanup(self.engine.dispose)
        self.store = TaskStore(self.engine, self.storage)
        self.serial = 0

    def create(self, owner='a', count=1, kind='DIPLOMA', *, package=False, pages=None):
        self.serial += 1
        files = [dict(data=f'synthetic-{self.serial}-{index}'.encode(),
                      name=f'fixture-{index}.png', mime='image/png', actual_source_page_count=pages)
                 for index in range(count)]
        return self.store.create_batch(files, [kind] * count if package else kind, owner)

    def raw(self, task_id):
        with self.engine.connect() as connection:
            return dict(connection.execute(text('SELECT * FROM tasks WHERE id=:id'),
                                           {'id': task_id}).mappings().one())

    def claim(self, kinds=CERTIFICATES, lane='certificate'):
        return self.store.claim_next(kinds, lane=lane)

    def complete(self, task):
        self.assertTrue(self.store.publish(task, dict(doc_type=task['doc_type'], status='COMPLETED',
                                                     fields=[], pages=[], review_issues=[], warnings=[])))

    def cancel(self, task_id):
        current = self.store.task(task_id)
        self.store.cancel(task_id, current['run_id'], current['result_revision'], 'synthetic-operator')

    def cursor(self, lane='certificate'):
        with self.engine.connect() as connection:
            return connection.execute(text('SELECT last_owner FROM document_queue_cursors WHERE lane=:lane'),
                                      {'lane': lane}).scalar_one_or_none()

    def test_large_batch_yields_next_turn_to_later_account(self):
        alice = self.create('a', 100)['task_ids']
        first = self.claim()
        bob = self.create('b')['task_ids'][0]
        self.assertEqual(first['id'], alice[0])
        self.complete(first)
        second = self.claim()
        self.assertEqual(second['id'], bob)
        self.complete(second)
        self.assertEqual(self.claim()['id'], alice[1])

    def test_single_page_guard_preserves_fair_head_and_cursor_until_lane_is_idle(self):
        first = self.create('a', pages=1)['task_ids'][0]
        report = self.create('b', kind='MEDICAL_REPORT', pages=22)['task_ids'][0]
        later = self.create('c', pages=1)['task_ids'][0]
        types = CERTIFICATES | {'MEDICAL_REPORT'}
        self.assertEqual(self.claim(types)['id'], first)
        self.assertIsNone(self.store.claim_next(types, lane='certificate', single_page_only=True))
        self.assertEqual(self.cursor(), 'a:a')
        self.assertEqual(self.raw(report)['status'], 'QUEUED')
        self.assertIsNone(self.raw(report)['active_started_at'])
        with self.engine.connect() as connection:
            self.assertIsNone(connection.execute(text('SELECT started_at FROM runs WHERE id=:id'),
                {'id': self.raw(report)['run_id']}).scalar_one())
        self.complete(self.raw(first))
        claimed = self.claim(types)
        self.assertEqual(claimed['id'], report)
        self.assertFalse(claimed['_batch_safe'])
        self.complete(claimed)
        self.assertEqual(self.store.claim_next(types, lane='certificate', single_page_only=True)['id'], later)

    def test_only_validated_single_page_non_medical_materials_are_batch_safe(self):
        for kind, pages, expected in [('DIPLOMA', 1, True), ('DIPLOMA', 2, False),
                ('DIPLOMA', None, False), ('DIPLOMA', True, False), ('MEDICAL_REPORT', 1, False)]:
            with self.subTest(kind=kind, pages=pages):
                identity = self.create('a', kind=kind, pages=pages)['task_ids'][0]
                if not expected:
                    self.assertIsNone(self.store.claim_next({kind}, single_page_only=True))
                claimed = self.store.claim_next({kind})
                self.assertEqual(claimed['id'], identity)
                self.assertIs(claimed['_batch_safe'], expected)
                self.complete(claimed)

    def test_three_accounts_rotate_with_stable_owner_ring(self):
        accounts = {owner: self.create(owner, 3)['task_ids'] for owner in ['b', 'a', 'c']}
        observed = []
        for _ in range(9):
            claimed = self.claim()
            observed.append(claimed['id'])
            self.complete(claimed)
        self.assertEqual(observed, [accounts[owner][index] for index in range(3) for owner in ['b', 'c', 'a']])
        self.assertIsNone(self.claim())

    def test_splitting_batches_does_not_create_extra_account_turns(self):
        alice = [self.create('a')['task_ids'][0] for _ in range(4)]
        bob = self.create('b', 2)['task_ids']
        observed = []
        for _ in range(4):
            task = self.claim()
            observed.append(task['id'])
            self.complete(task)
        self.assertEqual(observed, [alice[0], bob[0], alice[1], bob[1]])

    def test_same_timestamp_keeps_input_order_and_clock_changes_do_not_reorder(self):
        with patch('ocr_app.task_store.now', return_value='2026-10-16T03:00:00+00:00'):
            initial = self.create('a', 5)['task_ids']
        with patch('ocr_app.task_store.now', return_value='2020-01-01T00:00:00+00:00'):
            later = self.create('a')['task_ids'][0]
        identifiers = initial + [later]
        sequences = [self.raw(identifier)['enqueue_seq'] for identifier in identifiers]
        self.assertEqual(sequences, sorted(set(sequences)))
        observed = []
        for _ in identifiers:
            task = self.claim()
            observed.append(task['id'])
            self.complete(task)
        self.assertEqual(observed, identifiers)

    def test_rerun_joins_own_queue_tail_and_preserves_original_creation_time(self):
        old, pending = self.create('a', 2)['task_ids']
        task = self.claim()
        self.complete(task)
        before = self.raw(old)
        version = self.store.task(old)
        self.store.rerun(old, version['run_id'], version['result_revision'], 'a')
        after = self.raw(old)
        self.assertEqual(after['created_at'], before['created_at'])
        self.assertGreater(after['enqueue_seq'], self.raw(pending)['enqueue_seq'])
        self.assertNotEqual(after['run_id'], before['run_id'])
        next_task = self.claim()
        self.assertEqual(next_task['id'], pending)
        self.complete(next_task)
        self.assertEqual(self.claim()['id'], old)

    def test_append_and_duplicate_do_not_reset_existing_queue_position(self):
        package = self.create('a', 2, package=True)
        first, second = package['task_ids']
        before = self.raw(second)
        first_task = self.claim()
        bob = self.create('b')['task_ids'][0]
        user = {'user_id': 'a', 'role': 'operator'}
        appended = self.store.append_batch(package['batch_id'], [
            dict(data=self.storage.read(before['input_ref']), name='duplicate.png', mime='image/png'),
            dict(data=b'synthetic appended', name='appended.png', mime='image/png'),
        ], ['DIPLOMA', 'DIPLOMA'], 0, 'a', user=user, authorize=lambda connection: None)
        self.assertEqual(len(appended['task_ids']), 1)
        third = appended['task_ids'][0]
        self.assertEqual(self.raw(second)['enqueue_seq'], before['enqueue_seq'])
        self.assertEqual(self.raw(second)['queued_at'], before['queued_at'])
        self.assertGreater(self.raw(third)['enqueue_seq'], before['enqueue_seq'])
        self.complete(first_task)
        observed = []
        for _ in range(3):
            task = self.claim()
            observed.append(task['id'])
            self.complete(task)
        self.assertEqual(first_task['id'], first)
        self.assertEqual(observed, [bob, second, third])

    def test_document_lanes_have_independent_account_turns(self):
        a_cert = self.create('a', 2)['task_ids']
        b_cert = self.create('b')['task_ids'][0]
        b_paddle = self.create('b', 2, 'MEDICAL_REPORT')['task_ids']
        a_paddle = self.create('a', kind='GENERIC')['task_ids'][0]
        certificate = self.claim()
        medical = self.claim(PADDLE, 'medical')
        self.assertEqual((certificate['id'], medical['id']), (a_cert[0], b_paddle[0]))
        self.assertEqual((self.cursor(), self.cursor('medical')), ('a:a', 'a:b'))
        self.complete(certificate)
        self.complete(medical)
        self.assertEqual(self.claim()['id'], b_cert)
        self.assertEqual(self.claim(PADDLE, 'medical')['id'], a_paddle)

    def test_default_scope_uses_stable_type_set_key(self):
        alice = self.create('a', 2)['task_ids']
        bob = self.create('b')['task_ids'][0]
        first = self.store.claim_next(['DIPLOMA', 'DEGREE_CERT'])
        self.complete(first)
        second = self.store.claim_next(['DEGREE_CERT', 'DIPLOMA'])
        self.assertEqual((first['id'], second['id']), (alice[0], bob))
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT COUNT(*) FROM document_queue_cursors')).scalar_one(), 1)

    def test_default_all_and_explicit_all_share_a_turn(self):
        alice = self.create('a', 2)['task_ids']
        bob = self.create('b', kind='MEDICAL_REPORT')['task_ids'][0]
        first = self.store.claim_next()
        self.complete(first)
        self.assertEqual(self.cursor('all'), 'a:a')
        self.assertEqual(first['id'], alice[0])
        self.assertEqual(self.store.claim_next(lane='all')['id'], bob)

    def test_empty_claim_does_not_change_cursor_and_single_account_keeps_working(self):
        identifiers = self.create('a', 3)['task_ids']
        for identifier in identifiers:
            task = self.claim()
            self.assertEqual(task['id'], identifier)
            self.complete(task)
        saved = self.cursor()
        self.assertIsNone(self.claim())
        self.assertIsNone(self.store.claim_next(set(), lane='certificate'))
        self.assertEqual(self.cursor(), saved)
        next_id = self.create('a')['task_ids'][0]
        self.assertEqual(self.claim()['id'], next_id)

    def test_cancelled_and_stopped_queued_work_are_skipped(self):
        alice = self.create('a', 2)['task_ids']
        bob = self.create('b')['task_ids'][0]
        carol = self.create('c')['task_ids'][0]
        first = self.claim()
        self.complete(first)
        self.cancel(bob)
        with self.store.transaction() as connection:
            connection.execute(text("UPDATE tasks SET stop_code='WORKER_INTERRUPTED' WHERE id=:id"), {'id': carol})
        self.assertEqual(self.claim()['id'], alice[1])

    def test_deleted_last_owner_batch_does_not_block_the_next_account(self):
        old = self.create('b')
        next_id = self.create('c')['task_ids'][0]
        wrap = self.create('a')['task_ids'][0]
        first = self.claim()
        self.complete(first)
        version = self.store.task(first['id'])
        self.store.delete_batch(old['batch_id'], [dict(task_id=first['id'], run_id=version['run_id'],
            expected_revision=version['result_revision'])], 'synthetic-admin', authorize=lambda connection: None)
        self.assertEqual(self.cursor(), 'a:b')
        task = self.claim()
        self.assertEqual(task['id'], next_id)
        self.complete(task)
        self.assertEqual(self.claim()['id'], wrap)

    def test_absent_account_and_legacy_owners_keep_material_buckets(self):
        legacy = self.create('legacy-upload', 2)
        ordinary = self.create('a', 2)['task_ids']
        with self.store.transaction() as connection:
            connection.execute(text('UPDATE batches SET owner_id=NULL WHERE id=:id'), {'id': legacy['batch_id']})
        first = self.claim()
        self.assertEqual(first['id'], legacy['task_ids'][0])
        self.assertEqual(self.cursor(), 'l:')
        self.complete(first)
        second = self.claim()
        self.assertEqual(second['id'], ordinary[0])
        self.complete(second)
        third = self.claim()
        self.assertEqual(third['id'], legacy['task_ids'][1])
        self.complete(third)
        self.assertEqual(self.claim()['id'], ordinary[1])

    def test_reopening_database_preserves_cursor_and_remaining_order(self):
        alice = self.create('a', 2)['task_ids']
        bob = self.create('b')['task_ids'][0]
        first = self.claim()
        self.complete(first)
        self.engine.dispose()
        restarted = open_database(self.root)
        try:
            store = TaskStore(restarted, self.storage)
            second = store.claim_next(CERTIFICATES, lane='certificate')
            self.assertEqual(second['id'], bob)
            self.assertEqual(first['id'], alice[0])
        finally:
            restarted.dispose()

    def test_concurrent_claims_are_unique_and_each_waiting_account_gets_one_turn(self):
        tasks = {owner: self.create(owner, 2)['task_ids'] for owner in ['a', 'b', 'c']}
        barrier = threading.Barrier(3)
        def claim():
            barrier.wait(timeout=5)
            return self.claim()['id']
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: claim(), range(3)))
        self.assertCountEqual(results, [tasks[owner][0] for owner in ['a', 'b', 'c']])
        self.assertEqual(self.cursor(), 'a:c')
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM tasks WHERE status='PREPROCESSING'")).scalar_one(), 3)

    def test_failed_claim_transaction_does_not_advance_cursor_or_task(self):
        self.create('a', 2)
        bob = self.create('b')['task_ids'][0]
        first = self.claim()
        self.complete(first)
        before = self.raw(bob)
        def fail_commit(connection):
            raise OSError('synthetic claim commit failure')
        event.listen(self.engine, 'commit', fail_commit)
        try:
            with self.assertRaisesRegex(OSError, 'synthetic claim commit failure'):
                self.claim()
        finally:
            event.remove(self.engine, 'commit', fail_commit)
        self.assertEqual(self.cursor(), 'a:a')
        self.assertEqual(self.raw(bob), before)
        self.assertEqual(self.claim()['id'], bob)


if __name__ == '__main__':
    unittest.main()
