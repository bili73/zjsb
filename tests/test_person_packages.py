"""Person assignment, atomic append and presence-only pairing use synthetic inputs."""
import io
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from PIL import Image
from sqlalchemy import text
import test_business_api as base
import test_batch_ownership as ownership


class PersonPackagesTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    account = ownership.BatchOwnershipTests.account
    password = 'synthetic account password'

    def image_bytes(self, color):
        output = io.BytesIO()
        Image.new('RGB', (300, 200), color).save(output, format='PNG')
        return output.getvalue()

    def upload(self, headers, kind='DIPLOMA', person='测试人员'):
        return self.client.post('/api/v1/batches', headers=headers,
            data=dict(doc_type_hint=kind, person_name=person), files={'files': ('synthetic.png', self.image, 'image/png')})

    def append(self, batch, headers, kind='ID_CARD_BACK', revision=0, content=None):
        return self.client.post('/api/v1/batches/' + batch + '/append', headers=headers,
            data=dict(doc_type_hint=kind, expected_revision=str(revision)),
            files={'files': ('addition.png', content or self.image_bytes('blue'), 'image/png')})

    snapshot = ownership.BatchOwnershipTests.snapshot
    assert_business_unchanged = ownership.BatchOwnershipTests.assert_business_unchanged

    def test_explicit_person_is_encrypted_and_same_names_are_not_merged(self):
        account, headers, _ = self.account('alice')
        first = self.upload(headers).json()['batch_id']
        second = self.upload(headers).json()['batch_id']
        self.assertNotEqual(first, second)
        package = self.business.store.batch(first)
        self.assertEqual(package['person_name'], '测试人员')
        self.assertEqual(package['package_revision'], 0)
        self.assertEqual(package['id_card_pairing'], 'not_provided')
        with self.business.engine.connect() as c:
            ciphertext = c.execute(text('SELECT person_name_enc FROM batches WHERE id=:id'), {'id': first}).scalar_one()
        self.assertNotIn('测试人员'.encode(), ciphertext)
        self.assertEqual(self.business.storage.unpack(ciphertext), '测试人员')
        self.assertEqual(package['owner']['user_id'], account['user_id'])

    def test_queued_pair_presence_updates_and_append_keeps_original_task(self):
        _, headers, _ = self.account('alice')
        created = self.upload(headers, 'ID_CARD_FRONT').json()
        batch = created['batch_id']
        before = self.business.store.task(created['task_ids'][0])
        package = self.business.store.batch(batch)
        self.assertEqual(package['id_card_pairing'], 'missing_back')
        self.assertEqual(package['warnings'], [], 'the back is optional for front-only recognition')
        response = self.append(batch, headers)
        self.assertEqual(response.status_code, 202, response.text)
        package = self.business.store.batch(batch)
        self.assertEqual(package['id_card_pairing'], 'both_present')
        self.assertEqual(package['package_revision'], 1)
        self.assertEqual(package['warnings'], [])
        self.assertEqual(package['file_count'], 2)
        self.assertEqual(self.business.store.task(before['task_id']), before)
        self.assertEqual({t['doc_type'] for t in self.business.store.tasks(batch)}, {'ID_CARD_FRONT', 'ID_CARD_BACK'})
        stale = self.append(batch, headers, 'DEGREE_CERT', 0, self.image_bytes('green'))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'RESULT_VERSION_CONFLICT')

    def test_only_back_warns_front_and_legacy_batches_remain_unassigned(self):
        account, headers, _ = self.account('alice')
        batch = self.upload(headers, 'ID_CARD_BACK').json()['batch_id']
        self.assertEqual(self.business.store.batch(batch)['id_card_pairing'], 'missing_front')
        legacy = self.business.store.create_batch([dict(data=self.image, name='legacy.png', mime='image/png', actual_source_page_count=1)],
                                                 'DIPLOMA', account['user_id'])['batch_id']
        self.assertIsNone(self.business.store.batch(legacy)['person_name'])
        self.assertEqual(self.business.store.batch(legacy)['id_card_pairing'], 'unassigned')
        self.assertEqual(self.append(legacy, headers).status_code, 422)

    def test_front_only_exports_without_back_task_or_back_fields(self):
        from ocr_app.extraction import extract_result
        _, headers, _ = self.account('alice')
        created = self.upload(headers, 'ID_CARD_FRONT').json()
        result = extract_result([], 'ID_CARD_FRONT')
        values = dict(name='合成人员', gender='F', ethnicity='汉', birth_date='1949-12-31',
                      address='合成测试地址', id_number='11010519491231002X')
        for field in result['fields']:
            field.update(value=values[field['key']], value_origin='manual')
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE tasks SET status='NEED_REVIEW',result_enc=:value WHERE id=:id"),
                      dict(id=created['task_ids'][0], value=self.business.storage.pack(result)))
        package = self.business.store.batch(created['batch_id'])
        self.assertNotIn('MISSING_ID_BACK', [w['code'] for w in package['warnings']])
        self.assertEqual(package['file_count'], 1)
        self.assertTrue(self.business.store.task(created['task_ids'][0])['export_ready'])
        response = self.client.post('/api/v1/export', headers=headers, json=dict(batch_id=created['batch_id']))
        self.assertEqual(response.status_code, 200, response.text[:100] if response.status_code != 200 else '')
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(response.content))
        headings = [cell.value for cell in workbook.active[1]]
        self.assertNotIn('签发机关', headings)
        self.assertNotIn('有效期限止', headings)

    def test_duplicate_same_type_reuses_task_and_conflicting_type_is_rejected(self):
        _, headers, _ = self.account('alice')
        created = self.upload(headers).json()
        reused = self.append(created['batch_id'], headers, 'DIPLOMA', content=self.image)
        self.assertEqual(reused.status_code, 202, reused.text)
        self.assertEqual(reused.json()['task_ids'], [])
        self.assertEqual(self.business.store.batch(created['batch_id'])['file_count'], 1)
        before = self.snapshot()
        conflict = self.append(created['batch_id'], headers, 'ID_CARD_BACK', 1, self.image)
        self.assertEqual(conflict.status_code, 422)
        self.assert_business_unchanged(before)

    def test_owner_admin_viewer_and_revoked_session_boundaries(self):
        owner, headers, _ = self.account('alice')
        created = self.upload(headers).json()
        _, foreign, _ = self.account('bob')
        _, viewer, _ = self.account('viewer', 'viewer')
        _, admin, _ = self.account('admin', 'admin')
        before = self.snapshot()
        self.assertEqual(self.append(created['batch_id'], foreign).status_code, 404)
        self.assertEqual(self.append(created['batch_id'], viewer).status_code, 403)
        self.assertEqual(self.append(created['batch_id'], {}).status_code, 401)
        self.assert_business_unchanged(before)
        self.assertEqual(self.append(created['batch_id'], admin).status_code, 202)
        self.assertEqual(self.business.store.batch(created['batch_id'])['owner']['user_id'], owner['user_id'])

    def test_revocation_during_upload_admission_prevents_append(self):
        _, headers, token = self.account('alice')
        batch = self.upload(headers).json()['batch_id']
        from ocr_app.business import prepare_uploads
        before = self.snapshot()
        def revoked(*args):
            prepared = prepare_uploads(*args)
            self.business.accounts.logout(token)
            return prepared
        with patch('ocr_app.routes.prepare_uploads', side_effect=revoked):
            response = self.append(batch, headers)
        self.assertEqual(response.status_code, 401, response.text)
        self.assert_business_unchanged(before, allowed_success=('logout',))

    def test_invalid_file_or_person_is_atomic(self):
        _, headers, _ = self.account('alice')
        before = self.snapshot()
        self.assertEqual(self.upload(headers, person=' ').status_code, 422)
        self.assertEqual(self.upload(headers, person='x' * 81).status_code, 422)
        self.assert_business_unchanged(before)
        batch = self.upload(headers).json()['batch_id']
        before = self.snapshot()
        response = self.client.post('/api/v1/batches/' + batch + '/append', headers=headers,
            data=dict(doc_type_hint='DIPLOMA', expected_revision='0'), files=[
                ('files', ('valid.png', self.image_bytes('green'), 'image/png')),
                ('files', ('bad.png', b'not an image', 'image/png'))])
        self.assertEqual(response.status_code, 422)
        self.assert_business_unchanged(before)
        self.assertEqual(self.business.store.batch(batch)['package_revision'], 0)

    def test_concurrent_stale_appends_create_only_one_new_task(self):
        from ocr_app.task_store import TaskError
        owner, headers, _ = self.account('alice')
        batch = self.upload(headers).json()['batch_id']
        def append(color):
            try:
                return self.business.store.append_batch(batch, [dict(data=self.image_bytes(color), name='synthetic.png',
                    mime='image/png', actual_source_page_count=1)], 'DIPLOMA', 0, owner['user_id'],
                    user=owner, authorize=lambda c: None)
            except TaskError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(append, ['green', 'blue']))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn('RESULT_VERSION_CONFLICT', results)
        self.assertEqual(self.business.store.batch(batch)['file_count'], 2)

    def test_storage_failure_rolls_back_tasks_and_deletes_only_new_artifacts(self):
        _, headers, _ = self.account('alice')
        batch = self.upload(headers).json()['batch_id']
        before = self.snapshot()
        references = {p for p in self.business.root.rglob('*') if p.is_file() and p.suffix not in {'.sqlite3', '-wal', '-shm'}}
        original_put = self.business.storage.put
        calls = []
        def failing_put(data):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('synthetic storage failure')
            return original_put(data)
        with patch.object(self.business.storage, 'put', side_effect=failing_put):
            with self.assertRaises(OSError):
                self.business.store.append_batch(batch, [dict(data=self.image_bytes(color), name='synthetic.png',
                    mime='image/png', actual_source_page_count=1) for color in ['green', 'blue']],
                    'DIPLOMA', 0, 'operator', user=None, authorize=lambda c: None)
        self.assert_business_unchanged(before)
        self.assertEqual(self.business.store.batch(batch)['package_revision'], 0)
        after = {p for p in self.business.root.rglob('*') if p.is_file() and p.suffix not in {'.sqlite3', '-wal', '-shm'}}
        self.assertEqual(after, references)

    def test_expiry_tracks_remaining_materials_and_rechecks_pairing(self):
        _, headers, _ = self.account('alice')
        created = self.upload(headers, 'ID_CARD_FRONT').json()
        identifier = created['task_ids'][0]
        early = '2026-01-01T00:00:00+00:00'
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE tasks SET expires_at=:expiry,status='CANCELLED' WHERE id=:id"),
                      dict(id=identifier, expiry=early))
        added = self.append(created['batch_id'], headers).json()['task_ids'][0]
        self.assertEqual(self.business.store.task(identifier)['expires_at'], early)
        self.assertEqual(self.business.store.batch(created['batch_id'])['expires_at'], early)
        self.business.store.cleanup(at='2026-01-02T00:00:00+00:00')
        package = self.business.store.batch(created['batch_id'])
        self.assertEqual(package['file_count'], 1)
        self.assertEqual(package['expires_at'], self.business.store.task(added)['expires_at'])
        self.assertEqual(package['id_card_pairing'], 'missing_front')

    def test_append_preserves_saved_manual_result_run_and_expiry(self):
        from ocr_app.extraction import extract_result
        _, headers, _ = self.account('alice')
        created = self.upload(headers).json()
        identifier = created['task_ids'][0]
        result = extract_result([], 'DIPLOMA')
        next(f for f in result['fields'] if f['key'] == 'name').update(value='人工姓名', value_origin='manual')
        with self.business.store.transaction() as c:
            c.execute(text("UPDATE tasks SET status='NEED_REVIEW',result_enc=:value WHERE id=:id"),
                      dict(id=identifier, value=self.business.storage.pack(result)))
            before = c.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': identifier}).one()
        self.assertEqual(self.append(created['batch_id'], headers).status_code, 202)
        with self.business.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': identifier}).one(), before)
        self.assertEqual(next(f for f in self.business.store.result(identifier)['fields'] if f['key'] == 'name')['value'], '人工姓名')


class PersonPackageMigrationTests(unittest.TestCase):
    def test_migration_from_0005_preserves_history_and_is_restart_safe(self):
        from sqlalchemy import create_engine
        from alembic import command
        from alembic.config import Config
        from ocr_app.db import open_database
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'tasks.sqlite3'))
            config = Config()
            config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'backend/migrations'))
            with engine.begin() as c:
                config.attributes['connection'] = c
                command.upgrade(config, '0005')
                c.execute(text("INSERT INTO batches(id,created_at,name_enc,owner_id) VALUES ('legacy','2026-10-12',:cipher,'operator')"),
                          {'cipher': b'unchanged encrypted batch name'})
                before = c.execute(text('SELECT id,created_at,name_enc,owner_id,owner_snapshot_enc FROM batches')).all()
            engine.dispose()
            for _ in range(2):
                upgraded = open_database(root)
                try:
                    with upgraded.connect() as c:
                        self.assertEqual(c.execute(text('SELECT id,created_at,name_enc,owner_id,owner_snapshot_enc FROM batches')).all(), before)
                        self.assertEqual(c.execute(text('SELECT person_name_enc,package_revision FROM batches')).one(), (None, 0))
                        self.assertEqual(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), '0012')
                finally:
                    upgraded.dispose()


if __name__ == '__main__':
    unittest.main()
