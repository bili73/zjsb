"""Interrupted SQLite DDL must roll back with the Alembic revision."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.db import open_database


class MigrationAtomicityTests(unittest.TestCase):
    def interrupted_upgrade(self, revision, failed_statement):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = 'sqlite:///' + str(root / 'tasks.sqlite3')
            original = create_engine(url)
            config = Config()
            config.set_main_option('script_location', str(ROOT / 'backend/migrations'))
            try:
                with original.begin() as c:
                    c.exec_driver_sql('BEGIN IMMEDIATE')
                    config.attributes['connection'] = c
                    command.upgrade(config, revision)
                    c.execute(text("INSERT INTO web_users VALUES ('owner','synthetic','Original name','operator','original hash',1)"))
                    c.execute(text("INSERT INTO web_sessions VALUES ('original token hash','owner',2000000000)"))
                    c.execute(text("INSERT INTO batches(id,created_at,name_enc,owner_id) VALUES ('batch','2026-10-12',:name,'owner')"),
                              {'name': b'original encrypted batch name'})
                    if revision == '0006':
                        c.execute(text('UPDATE batches SET person_name_enc=:person'), {'person': b'original encrypted person name'})
                    c.execute(text("""INSERT INTO tasks(id,batch_id,run_id,status,created_at,updated_at,expires_at,
                        content_hash,doc_type,input_ref,meta_enc,options_enc,result_enc)
                        VALUES ('task','batch','run','NEED_REVIEW','2026-10-12','2026-10-12','2026-10-19',
                        'original content hash','DIPLOMA','original input reference',:blob,:blob,:blob)"""),
                        {'blob': b'original encrypted task value'})
                    before = {table: (list(c.execute(text('SELECT * FROM ' + table)).keys()),
                                      c.execute(text('SELECT * FROM ' + table)).all())
                              for table in ['batches', 'tasks', 'web_users', 'web_sessions']}
                    schema = c.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").all()
            finally:
                original.dispose()

            failed_engine = create_engine(url)
            def interrupt(c, cursor, statement, parameters, context, many):
                if statement == failed_statement:
                    raise RuntimeError('synthetic interrupted migration')
            event.listen(failed_engine, 'before_cursor_execute', interrupt)
            try:
                with patch('ocr_app.db.create_engine', return_value=failed_engine), \
                        patch.object(failed_engine, 'dispose', wraps=failed_engine.dispose) as disposed:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic interrupted migration'):
                        open_database(root)
                    inspection = create_engine(url)
                    try:
                        with inspection.connect() as c:
                            self.assertEqual(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), revision)
                            self.assertEqual(c.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").all(), schema)
                            for table, (_, rows) in before.items():
                                self.assertEqual(c.execute(text('SELECT * FROM ' + table)).all(), rows)
                    finally:
                        inspection.dispose()
                    disposed.assert_called_once_with()
            finally:
                failed_engine.dispose()

            # A subsequent startup must succeed without duplicate-column repair.
            for _ in range(2):
                restarted = open_database(root)
                try:
                    with restarted.connect() as c:
                        self.assertEqual(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), '0012')
                        for table, (columns, rows) in before.items():
                            self.assertEqual(c.execute(text('SELECT ' + ','.join(columns) + ' FROM ' + table)).all(), rows)
                        self.assertEqual(c.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
                finally:
                    restarted.dispose()

    def test_0006_interruption_rolls_back_first_column_and_preserves_old_database(self):
        self.interrupted_upgrade('0005', 'ALTER TABLE batches ADD COLUMN package_revision INTEGER NOT NULL DEFAULT 0')

    def test_0007_interruption_rolls_back_package_flag_and_preserves_named_package(self):
        self.interrupted_upgrade('0006', 'UPDATE batches SET is_person_package=1 WHERE person_name_enc IS NOT NULL')

    def test_0010_interruption_preserves_tasks_and_settings(self):
        self.interrupted_upgrade('0009', 'INSERT INTO retention_settings VALUES (1,7,0)')

    def test_0011_interruption_rolls_back_audit_columns_without_rewriting_history(self):
        self.interrupted_upgrade('0010', 'ALTER TABLE audit ADD COLUMN context_enc BLOB')

    def test_0012_interruption_rolls_back_queue_columns_and_preserves_results(self):
        self.interrupted_upgrade('0011', 'CREATE INDEX tasks_enqueue ON tasks(enqueue_seq)')

    def test_0012_legacy_order_uses_rerun_update_without_inventing_enqueue_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'tasks.sqlite3'))
            config = Config()
            config.set_main_option('script_location', str(ROOT / 'backend/migrations'))
            with engine.begin() as c:
                c.exec_driver_sql('BEGIN IMMEDIATE')
                config.attributes['connection'] = c
                command.upgrade(config, '0011')
                c.execute(text("INSERT INTO batches(id,created_at,name_enc,owner_id) VALUES ('batch','2026-10-16',:blob,'owner')"),
                          {'blob': b'unchanged batch'})
                cases = [('rerun', 'QUEUED', '2026-01-01', '2026-10-16'),
                         ('b', 'QUEUED', '2026-10-15', '2026-10-15'),
                         ('a', 'QUEUED', '2026-10-15', '2026-10-15'),
                         ('saved', 'NEED_REVIEW', '2026-10-01', '2026-10-16')]
                for task, status, created, updated in cases:
                    c.execute(text('''INSERT INTO tasks(id,batch_id,run_id,status,created_at,updated_at,expires_at,
                        content_hash,doc_type,input_ref,meta_enc,options_enc,result_enc)
                        VALUES (:id,'batch',:id,:status,:created,:updated,'2027-01-01',
                        :id,'DIPLOMA','original reference',:blob,:blob,:blob)'''),
                        dict(id=task, status=status, created=created, updated=updated, blob=b'original encrypted value'))
                result = c.execute(text('SELECT * FROM tasks ORDER BY id'))
                columns, before = ','.join(result.keys()), result.all()
            engine.dispose()
            for _ in range(2):
                upgraded = open_database(root)
                try:
                    with upgraded.connect() as c:
                        self.assertEqual(c.execute(text('SELECT ' + columns + ' FROM tasks ORDER BY id')).all(), before)
                        self.assertEqual(c.execute(text("SELECT id FROM tasks WHERE status='QUEUED' ORDER BY enqueue_seq")).scalars().all(),
                                         ['a', 'b', 'rerun'])
                        self.assertEqual(c.execute(text('SELECT queued_at FROM tasks')).scalars().all(), [None] * 4)
                        self.assertEqual(c.execute(text('SELECT COUNT(*) FROM document_queue_cursors')).scalar_one(), 0)
                finally:
                    upgraded.dispose()

    def test_0009_interruption_rolls_back_preferences_without_changing_existing_records(self):
        self.interrupted_upgrade('0008', "UPDATE alembic_version SET version_num='0009' WHERE alembic_version.version_num = '0008'")


if __name__ == '__main__':
    unittest.main()
