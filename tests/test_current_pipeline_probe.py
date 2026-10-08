import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('current_probe', ROOT / 'scripts/probe_current_pipeline.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class CurrentPipelineProbeTests(unittest.TestCase):
    def case(self):
        return dict(id='synthetic', doc_type='DIPLOMA', fields=[
            dict(key='graduate_date', required=True), dict(key='name', required=True),
            dict(key='study_mode', required=False), dict(key='principal', required=True)],
            reference=dict(graduate_date=dict(status='present', value='2026年6月'),
                           name=dict(status='present', value='合成值'),
                           study_mode=dict(status='absent', value=None),
                           principal=dict(status='uncertain', value=None)))

    def test_score_keeps_present_absent_uncertain_separate_and_no_values_public(self):
        rows, stats = probe.score_case(self.case(), {'fields': [
            dict(key='graduate_date', value='2026-06'), dict(key='name', value='合成值'),
            dict(key='study_mode', value='PRIVATE_VALUE')]}, [])
        self.assertEqual((stats['field_correct'], stats['field_total']), (2, 2))
        self.assertEqual(stats['false_positive'], 1)
        self.assertEqual(stats['unscored'], 1)
        self.assertEqual(stats['required_reference_missing'], 0)
        self.assertEqual(stats['runtime_required_missing'], 1)
        self.assertNotIn('PRIVATE_VALUE', json.dumps(rows))
        self.assertNotIn('value', rows[0])

    def test_failed_no_result_keeps_denominator_and_partial_is_scored(self):
        _, empty = probe.score_case(self.case(), None, [])
        self.assertEqual((empty['field_total'], empty['missing'], empty['field_accuracy']), (2, 2, 0))
        _, partial = probe.score_case(self.case(), {'status': 'FAILED', 'fields': [dict(key='name', value='合成值')]}, [])
        self.assertEqual((partial['field_total'], partial['field_correct'], partial['missing']), (2, 1, 1))

    def test_duplicate_keys_and_explicit_conflicts_cannot_win_last(self):
        for fields in [[dict(key='name', value='合成值'), dict(key='name', value='不同值')],
                       [dict(key='name', value='合成值', review_issues=[dict(code='CONFLICT')])]]:
            rows, stats = probe.score_case(self.case(), {'fields': fields}, [])
            self.assertTrue(next(r for r in rows if r['field'] == 'name')['conflict'])
            self.assertEqual(stats['field_correct'], 0)

    def test_medical_basic_is_unknown_and_blood_duplicates_conflict(self):
        case = dict(id='report-test', doc_type='MEDICAL_REPORT', blood_page=12,
                    blood_reference={'TEST': '1.00↑'}, summary_reference=dict(scope='follow_up_required', declared_count=2, page=8))
        result = dict(items=[dict(alias='TEST', result_raw='1.00 ↑', source=dict(page=12)),
                             dict(alias='TEST', result_raw='2.00↑', source=dict(page=12))])
        rows, stats = probe.score_case(case, result, [])
        self.assertTrue(rows[0]['conflict'])
        self.assertEqual(stats['field_total'], 1)
        self.assertIsNone(stats['medical_basic_accuracy'])
        self.assertIsNone(stats['summary_declared'])

    def test_identical_blood_values_at_different_sources_still_conflict(self):
        case = dict(id='report-test', doc_type='MEDICAL_REPORT', blood_page=12,
                    blood_reference={'TEST': '1.00'}, summary_reference=dict(scope='follow_up_required', declared_count=2, page=8))
        result = dict(items=[dict(alias='TEST', result_raw='1.00', source=dict(page=12, region_id='a')),
                             dict(alias='TEST', result_raw='1.00', source=dict(page=12, region_id='b'))])
        rows, stats = probe.score_case(case, result, [])
        self.assertEqual((rows[0]['outcome'], rows[0]['duplicate_match_count']), ('missing', 2))
        self.assertEqual(stats['field_accuracy'], 0)

    def test_output_must_be_new_and_under_own_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); base = root / 'output'; base.mkdir()
            production = root / '.runtime/data'; production.mkdir(parents=True)
            sentinel = production / 'history'; sentinel.write_bytes(b'UNCHANGED')
            with self.assertRaises(probe.ProbeError):
                probe.isolated_output(production, base=base)
            out = probe.isolated_output(base / 'new-run', base=base)
            with self.assertRaises(FileExistsError):
                probe.isolated_output(out, base=base)
            self.assertEqual(sentinel.read_bytes(), b'UNCHANGED')

    def test_frozen_hash_rejected_before_decryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'private').mkdir()
            (root / 'protocol.json').write_text(json.dumps(dict(fixture_sha256='incorrect')))
            (root / 'private/fixture.enc').write_bytes(b'encrypted')
            with patch.object(probe, 'read_only_storage') as read:
                with self.assertRaisesRegex(probe.ProbeError, 'FROZEN_FIXTURE_HASH_MISMATCH'):
                    probe.frozen(root)
                read.assert_not_called()

    def test_published_reads_task_not_run_and_checks_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); data = out / 'private/data'; data.mkdir(parents=True)
            with sqlite3.connect(data / 'tasks.sqlite3') as db:
                db.execute('CREATE TABLE tasks(id TEXT,run_id TEXT,result_enc BLOB,pages_enc BLOB,revision INTEGER)')
                db.execute('CREATE TABLE attempts(run_id TEXT,payload_enc BLOB,created_at TEXT)')
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)', ('task', 'run', b'published', b'pages', 5))
            db.close()
            with patch.object(probe, 'read_only_storage') as storage:
                storage.return_value.unpack.side_effect = lambda data, default=None: data
                self.assertEqual(probe.published(out, 'task', 'run', 5)[0], b'published')
                with self.assertRaisesRegex(probe.ProbeError, 'RESULT_VERSION_MISMATCH'):
                    probe.published(out, 'task', 'old', 5)
                with self.assertRaisesRegex(probe.ProbeError, 'RESULT_VERSION_MISMATCH'):
                    probe.published(out, 'task', 'run', 4)

    def test_review_contract_accepts_optional_absence_but_not_required_or_conflict_without_review(self):
        optional = dict(key='study_mode', value=None, need_review=False, review_issues=[])
        self.assertTrue(probe.review_contract_valid([optional], {'name'}))
        self.assertFalse(probe.review_contract_valid([{**optional, 'key': 'name'}], {'name'}))
        missing = dict(key='name', value=None, need_review=True, review_issues=[dict(code='MISSING')])
        self.assertTrue(probe.review_contract_valid([optional, missing], {'name'}))
        conflict = dict(key='name', value=None, need_review=True, review_issues=[dict(code='CONFLICT')])
        self.assertTrue(probe.review_contract_valid([conflict], {'name'}))
        self.assertFalse(probe.review_contract_valid([{**conflict, 'need_review': False}], {'name'}))
        self.assertFalse(probe.review_contract_valid([{**optional, 'need_review': 0}], set()))


if __name__ == '__main__':
    unittest.main()
