"""Real database failures and privacy-preserving frontend report context."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

from sqlalchemy import create_engine, text
import test_diagnostic_service as existing
from ocr_app import diagnostics as d
from ocr_app.diagnostic_service import DiagnosticService


class DatabaseContextTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'OCR_LOG_LEVEL': 'ERROR'}))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def connect(self, path=':memory:'):
        connection = sqlite3.connect(path, timeout=0)
        self.addCleanup(connection.close)
        return connection

    def failure(self, connection, sql, expected, code):
        try:
            connection.execute(sql)
        except sqlite3.Error as error:
            row = d.safe_exception(error)[0]
            self.assertEqual(row['type'], type(error).__name__)
            self.assertEqual(row['database_error'], expected)
            self.assertEqual(row['sqlite_errorcode'], code)
            self.assertNotIn('PRIVATE', json.dumps(row))
            return error
        self.fail('Expected a real SQLite failure')

    def test_native_schema_constraint_readonly_errors_keep_only_safe_details(self):
        connection = self.connect()
        self.failure(connection, 'SELECT * FROM PRIVATE_missing', 'missing_table', sqlite3.SQLITE_ERROR)
        connection.execute('CREATE TABLE PRIVATE_table (value INTEGER UNIQUE)')
        self.failure(connection, 'SELECT PRIVATE_column FROM PRIVATE_table', 'missing_column', sqlite3.SQLITE_ERROR)
        connection.execute('INSERT INTO PRIVATE_table VALUES (1)')
        self.failure(connection, 'INSERT INTO PRIVATE_table VALUES (1)', 'constraint', sqlite3.SQLITE_CONSTRAINT_UNIQUE)
        connection.execute('PRAGMA query_only = ON')
        self.failure(connection, 'INSERT INTO PRIVATE_table VALUES (2)', 'readonly', sqlite3.SQLITE_READONLY)

    def test_native_busy_and_corrupt_errors_keep_numeric_code(self):
        path = self.root / 'PRIVATE.sqlite3'
        first, second = self.connect(path), self.connect(path)
        first.execute('CREATE TABLE PRIVATE_table (value INTEGER)')
        first.execute('BEGIN EXCLUSIVE')
        self.failure(second, 'SELECT * FROM PRIVATE_table', 'busy', sqlite3.SQLITE_BUSY)
        malformed = self.root / 'PRIVATE_corrupt.sqlite3'
        malformed.write_bytes(b'PRIVATE invalid database' * 100)
        self.failure(self.connect(malformed), 'SELECT * FROM PRIVATE_table', 'corrupt', sqlite3.SQLITE_NOTADB)

    def test_sqlalchemy_chain_survives_query_archive_and_offline_export(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        logger = d.init_diagnostics(self.root / 'diagnostics', 'api')
        with engine.connect() as connection:
            try:
                connection.execute(text('SELECT * FROM PRIVATE_missing WHERE value=:secret'), {'secret': 'PRIVATE_PARAMETER'})
            except Exception as error:
                logger.exception('pipeline_failed', error)
        persisted = json.loads(logger.path.read_text())
        self.assertEqual([error['type'] for error in persisted['exceptions']], ['OperationalError', 'OperationalError'])
        self.assertEqual(persisted['exceptions'][-1]['database_error'], 'missing_table')
        self.assertNotIn('PRIVATE', json.dumps(persisted))
        # Export must sanitize disk contents again, even when fields were injected after logging.
        persisted['exceptions'][0].update(database_error='PRIVATE_TABLE', sqlite_errorcode='PRIVATE', message='PRIVATE_SQL')
        persisted['exceptions'][-1]['sql'] = 'PRIVATE_SQL'
        logger.path.write_text(json.dumps(persisted) + '\n')
        service = DiagnosticService(logger)
        service.tick()
        rows = service.query()['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['exceptions'][-1]['sqlite_errorcode'], sqlite3.SQLITE_ERROR)
        self.assertNotIn('PRIVATE', json.dumps(rows))
        offline = self.root / 'offline.zip'
        d.collect_diagnostics(logger.root, offline)
        for data in (service.bundle()[0], offline.read_bytes()):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                exported = [json.loads(line) for name in archive.namelist() if name.endswith('.jsonl')
                            for line in archive.read(name).decode().splitlines()]
                self.assertTrue(exported)
                self.assertTrue(all(row['exceptions'][-1]['database_error'] == 'missing_table' for row in exported))
                self.assertNotIn('PRIVATE', json.dumps(exported))

    def test_unknown_exception_prose_and_invalid_context_are_not_collected(self):
        class PrivateFailure(Exception):
            pass
        error = PrivateFailure('no such table: PRIVATE')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        row = d.safe_exception(error)[0]
        self.assertEqual(row['type'], 'Exception')
        self.assertNotIn('database_error', row)
        self.assertNotIn('sqlite_errorcode', row)
        self.assertEqual(d.safe_context(dict(frontend_build='https://PRIVATE/index-abcdefgh.js',
                                            frontend_exception_type='PRIVATE', browser_event='PRIVATE',
                                            database_error='PRIVATE', sqlite_errorcode=True)), {})


class FrontendContextTests(unittest.TestCase):
    setUp = existing.DiagnosticAPITests.setUp
    account = existing.DiagnosticAPITests.account
    password = existing.DiagnosticAPITests.password

    def test_optional_metadata_survives_reporting_query_and_bundle(self):
        _, headers, _ = self.account('context', 'viewer')
        legacy = dict(origin='window', operation='interface', code='CLIENT_ERROR', client_error_id=str(uuid.uuid4()))
        url = '/api/v1/diagnostics/frontend'
        self.assertEqual(self.client.post(url, json=legacy, headers=headers).status_code, 202)
        body = dict(legacy, client_error_id=str(uuid.uuid4()), line=12, column=345,
                    exception_type='TypeError', browser_event='javascript_error', frontend_build='b_Abc_1234')
        response = self.client.post(url, json=body, headers=headers)
        self.assertEqual(response.status_code, 202, response.text)
        context = self.service.query(error_id=body['client_error_id'])['items'][0]['context']
        self.assertEqual(context['frontend_exception_type'], 'TypeError')
        self.assertEqual(context['browser_event'], 'javascript_error')
        self.assertEqual(context['frontend_build'], 'b_Abc_1234')
        self.assertEqual((context['frontend_line'], context['frontend_column']), (12, 345))
        with zipfile.ZipFile(io.BytesIO(self.service.bundle(error_id=body['client_error_id'])[0])) as archive:
            self.assertEqual(json.loads(archive.read('events.jsonl'))['context'], context)
        # Untrusted new fields must not enter either the log or a saved-record export.
        for values in [dict(exception_type='PRIVATE'), dict(exception_type=['TypeError']),
                       dict(browser_event='PRIVATE'), dict(frontend_build='https://PRIVATE'),
                       dict(frontend_build='b_short'), dict(message='PRIVATE')]:
            response = self.client.post(url, json=dict(body, **values), headers=headers)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn('PRIVATE', self.logger.path.read_text())


if __name__ == '__main__':
    unittest.main()
