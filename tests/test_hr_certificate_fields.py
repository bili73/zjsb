"""HR public field profile: evidence and historical encrypted results stay intact."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.api import create_app
from ocr_app.business import Business
from ocr_app.extraction import extract_fields, extract_result
from test_business_api import FakeRuntime
from test_pipeline_schema import json_schema


def fields(text, kind='DIPLOMA'):
    return {field['key']: field for field in extract_fields([dict(text=text, page=1)], kind)}


class HRCertificateFieldsTests(unittest.TestCase):
    def test_diploma_has_eleven_keys_and_six_missing_required_fields(self):
        result = fields('校长：测试乙\n学习形式：函授')
        self.assertEqual(set(result), {'name', 'gender', 'birth_date', 'school_name', 'major',
            'certificate_no', 'education_level', 'duration', 'enroll_date', 'graduate_date', 'issue_date'})
        self.assertEqual(sum(any(i['code'] == 'MISSING' for i in f['review_issues']) for f in result.values()), 6)

    def test_degree_keeps_study_mode_and_retired_labels_still_bound_diploma_values(self):
        self.assertEqual(fields('学习形式：函授', 'DEGREE_CERT')['study_mode']['value'], '函授')
        for key, text, expected in (
            ('certificate_no', '证书编号：000123 校长：测试乙', '000123'),
            ('major', '专业：测试工程 学习形式：全日制', '测试工程'),
            ('school_name', '校名：示例大学 校长：测试乙', '示例大学'),
        ):
            with self.subTest(field=key):
                self.assertEqual(fields(text)[key]['value'], expected)

    def test_new_results_keep_original_evidence(self):
        text = '校长：测试乙\n学习形式：函授'
        result = extract_result([dict(text=text, page=1)], 'DIPLOMA')
        self.assertFalse({'principal', 'study_mode'} & {f['key'] for f in result['fields']})
        self.assertEqual(result['generic']['full_text'], text)
        self.assertEqual(result['generic']['blocks'][0]['text'], text)


class HRHistoricalProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.business = Business(root / 'data', key=b'H' * 32)
        self.addCleanup(self.business.close)
        self.client = self.enterContext(TestClient(create_app(FakeRuntime(), root / 'dist', root / 'session', self.business),
            base_url='http://127.0.0.1', client=('127.0.0.1', 12345)))
        self.headers = {'X-API-Key': self.business.accounts.current_key()}

    def publish_legacy(self, kind):
        text = '校长：测试乙\n学习形式：函授'
        created = self.business.store.create_batch([dict(data=b'synthetic original', name='synthetic.png', mime='image/png')], kind, self.business.accounts.accounts[0]['user_id'])
        task_id = created['task_ids'][0]
        task = self.business.store.claim_next()
        payload = extract_result([dict(text=text, page=1)], kind)
        for key, value in [('principal', '测试乙'), ('study_mode', '函授')]:
            if key not in {f['key'] for f in payload['fields']}:
                payload['fields'].append(dict(key=key, label=key, value=value, confidence=None,
                    confidence_method='unavailable', need_review=True, review_issues=[]))
        payload.update(status='NEED_REVIEW', pages=[], warnings=[])
        self.assertTrue(self.business.store.publish(task, payload))
        return task_id, text

    def snapshot(self):
        with self.business.engine.connect() as connection:
            return {table: [tuple(row) for row in connection.exec_driver_sql('SELECT * FROM ' + table)]
                    for table in ('tasks', 'runs', 'audit')}

    def test_historical_http_projection_preserves_ciphertext_revision_and_original(self):
        task_id, text = self.publish_legacy('DIPLOMA')
        before = self.snapshot()
        blobs = {p.name: p.read_bytes() for p in self.business.storage.blobs.iterdir()}
        for _ in range(2):
            response = self.client.get(f'/api/v1/tasks/{task_id}/result', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(len(result['fields']), 11)
            self.assertFalse({'principal', 'study_mode'} & {f['key'] for f in result['fields']})
            self.assertEqual(result['generic']['full_text'], text)
            self.assertEqual(result['generic']['blocks'][0]['text'], text)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({p.name: p.read_bytes() for p in self.business.storage.blobs.iterdir()}, blobs)
        with self.business.engine.connect() as connection:
            raw = self.business.storage.unpack(connection.exec_driver_sql('SELECT result_enc FROM tasks').scalar_one())
        self.assertTrue({'principal', 'study_mode'} <= {f['key'] for f in raw['fields']})

    def test_historical_degree_is_not_filtered(self):
        task_id, _ = self.publish_legacy('DEGREE_CERT')
        response = self.client.get(f'/api/v1/tasks/{task_id}/result', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = {f['key']: f for f in response.json()['fields']}
        self.assertEqual(result['study_mode']['value'], '函授')

    def test_complete_extracted_medical_http_payload_matches_task_result_schema(self):
        from test_hr_medical_profile import PERSONAL, HRMedicalProfileTests, block, table
        evidence = [block('一、个人信息', 7, .1), block(table(PERSONAL), 7, .2)]
        evidence += HRMedicalProfileTests().summary_evidence([['项目甲', '4↑', 'B']])
        payload = extract_result(evidence, 'MEDICAL_REPORT')
        created = self.business.store.create_batch([dict(data=b'synthetic medical original',
            name='synthetic-medical.pdf', mime='application/pdf')], 'MEDICAL_REPORT', self.business.accounts.accounts[0]['user_id'])
        self.assertTrue(self.business.store.publish(self.business.store.claim_next(),
            dict(payload, status='NEED_REVIEW', pages=[], warnings=[])))
        response = self.client.get(f"/api/v1/tasks/{created['task_ids'][0]}/result", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        schema = json_schema(yaml.safe_load((ROOT / 'openapi.yaml').read_text(encoding='utf-8')))
        self.assertEqual(self.client.get('/health').json()['version'], schema['info']['version'])
        jsonschema.Draft7Validator(dict(schema, **{'$ref': '#/components/schemas/TaskResult'}),
            format_checker=jsonschema.FormatChecker()).validate(result)
        from ocr_app.doc_profiles import profile
        expected = {f['key'] for f in profile('MEDICAL_REPORT')}
        self.assertEqual(set(result['basic_info']), expected)
        self.assertEqual({f['key']: f for f in result['fields']}, result['basic_info'])
        self.assertNotIn('work_unit', result['basic_info'])
        self.assertIn('示例单位', result['generic']['full_text'])
        self.assertIn('未婚', result['generic']['full_text'])
        self.assertEqual(result['items'][0]['risk_grade'], 'B')
        self.assertEqual(result['items'][0]['diagnosis'], '报告诊断甲')
        finding = result['report_summary']['findings'][0]
        self.assertEqual((finding['risk_grade'], finding['result_raw']), ('/', '4↑'))
        self.assertEqual(finding['result_sources'][0]['page'], 3)
        self.assertIsNone(result['stats']['total'])
        self.assertEqual(result['status'], 'NEED_REVIEW')
        legacy = copy.deepcopy(result)
        for key in ('institution', 'report_date', 'exam_projects'):
            legacy['basic_info'].pop(key)
        legacy['fields'] = [f for f in legacy['fields'] if f['key'] not in {'institution', 'report_date'}]
        for item in legacy['items'] + legacy['abnormal_summary']:
            for key in ('risk_grade', 'diagnosis', 'diagnosis_sources'):
                item.pop(key, None)
        for item in legacy['report_summary']['findings']:
            for key in ('risk_grade', 'diagnosis', 'result_raw', 'result_sources', 'need_review', 'review_issues'):
                item.pop(key, None)
        jsonschema.Draft7Validator(dict(schema, **{'$ref': '#/components/schemas/TaskResult'}),
            format_checker=jsonschema.FormatChecker()).validate(legacy)

    def test_phone_values_candidates_and_evidence_remain_full_without_rewriting_storage(self):
        for phone in ('13800000000', '138 0000 0000', '+86 138-0000-0000', '（+86）13800000000', None):
            with self.subTest(phone_format=phone):
                payload = extract_result([dict(page=1, text='<table><tr><td>项目名称</td><td>检测结果</td><td>风险等级</td><td>异常诊断</td></tr>'
                    '<tr><td>合成项目</td><td>2</td><td>B</td><td>合成诊断联系电话13800000000</td></tr></table>')], 'MEDICAL_REPORT')
                from ocr_app.extraction import _field
                field = _field('phone','联系电话',[],False)
                payload['fields'].append(field)
                payload['basic_info']['phone'] = field
                region_id = str(uuid4())
                evidence = '联系方式：13800000000；候选：13900000001；检验序列：13123456789'
                field.update(value=phone, candidates=[dict(value='139 0000 0001', confidence=None,
                    confidence_method='unavailable')], source=dict(page=1, region_id=region_id,
                    bbox=[.1,.2,.3,.4], bbox_kind='cell', extraction_method='pdf_text', raw_text=evidence))
                if phone is None:
                    field['candidates'].append(dict(value='13800000000', confidence=None, confidence_method='unavailable'))
                payload['generic']['full_text'] = evidence
                payload['generic']['blocks'][0]['text'] = evidence
                created = self.business.store.create_batch([dict(data=b'phone synthetic', name='phone.pdf',
                    mime='application/pdf')], 'MEDICAL_REPORT', self.business.accounts.accounts[0]['user_id'])
                self.assertTrue(self.business.store.publish(self.business.store.claim_next(),
                    dict(payload, status='NEED_REVIEW', pages=[], warnings=[])))
                before = self.snapshot()
                for query in ('', '?items_filter=all', '?items_filter=abnormal', '?items_filter=unknown&include_normal_summary=false'):
                    response = self.client.get(f"/api/v1/tasks/{created['task_ids'][0]}/result{query}", headers=self.headers)
                    self.assertEqual(response.status_code, 200)
                    value = response.json()
                    self.assertNotIn('phone', value['basic_info'])
                    self.assertFalse(any(f['key']=='phone' for f in value['fields']))
                    for public_text in (value['generic']['full_text'], value['generic']['blocks'][0]['text']):
                        self.assertIn('13800000000', public_text)
                        self.assertIn('13900000001', public_text)
                        self.assertIn('13123456789', public_text)
                    if value['items']:
                        self.assertIn('13800000000', value['items'][0]['diagnosis'])
                self.assertEqual(before, self.snapshot())

    def test_unknown_phone_does_not_trigger_global_eleven_digit_masking(self):
        payload = extract_result([dict(page=1, text='检验序列：13123456789')], 'MEDICAL_REPORT')
        payload['basic_info']['phone'] = dict(key='phone',value='日期2026-10-08')
        created = self.business.store.create_batch([dict(data=b'unknown phone', name='unknown.pdf', mime='application/pdf')],
            'MEDICAL_REPORT', self.business.accounts.accounts[0]['user_id'])
        self.assertTrue(self.business.store.publish(self.business.store.claim_next(), dict(payload, status='NEED_REVIEW', pages=[], warnings=[])))
        value = self.client.get(f"/api/v1/tasks/{created['task_ids'][0]}/result", headers=self.headers).json()
        self.assertNotIn('phone', value['basic_info'])
        self.assertIn('13123456789', value['generic']['full_text'])


class HRMedicalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json_schema(yaml.safe_load((ROOT / 'openapi.yaml').read_text(encoding='utf-8')))

    def validate(self, name, value):
        jsonschema.Draft7Validator(dict(self.schema, **{'$ref': '#/components/schemas/' + name}),
            format_checker=jsonschema.FormatChecker()).validate(value)

    def test_medical_grade_diagnosis_contract_accepts_new_and_legacy_items(self):
        source = dict(page=1, extraction_method='pdf_text')
        item = dict(item_id=str(uuid4()), name='合成项目', result_raw='检测原文',
                    abnormal_flag='ABNORMAL', abnormal_basis='report_grade', reported_abnormal_marker=None,
                    confidence=None, confidence_method='unavailable', need_review=True, review_issues=[],
                    risk_grade='B', diagnosis='报告诊断原文', diagnosis_sources=[source])
        self.validate('MedicalItem', item)
        legacy = {k: v for k, v in item.items() if k not in {'risk_grade', 'diagnosis', 'diagnosis_sources'}}
        legacy['abnormal_basis'] = 'report_marker'
        self.validate('MedicalItem', legacy)
        invalid = copy.deepcopy(item)
        invalid['grade'] = 'invented extra field'
        with self.assertRaises(jsonschema.ValidationError):
            self.validate('MedicalItem', invalid)

    def test_personal_additions_are_optional_without_new_missing_required_issues(self):
        result = extract_result([dict(page=1, text='体检报告')], 'MEDICAL_REPORT')
        for key in ('institution', 'report_date', 'height', 'weight', 'blood_pressure', 'blood_routine',
                    'urine_routine', 'ecg', 'dr_imaging', 'abdominal_ultrasound', 'liver_function', 'exam_project_count'):
            field = result['basic_info'][key]
            self.assertIsNone(field['value'])
            self.assertFalse(any(issue['code'] == 'MISSING' for issue in field['review_issues']))
        self.assertEqual(sum(any(i['code'] == 'MISSING' for i in field['review_issues'])
                             for field in result['fields']), 3)

    def test_finding_preserves_unlinked_detection_and_review_with_optional_compatibility(self):
        finding = dict(finding_id=str(uuid4()), reported_number='1', text='合成结论', sources=[dict(page=2)],
                       risk_grade=None, diagnosis='合成诊断', result_raw=None, result_sources=[], need_review=True,
                       review_issues=[dict(issue_id=str(uuid4()), code='MISSING', message='检测结果未唯一对应', can_accept=False)])
        self.validate('ReportFinding', finding)
        self.validate('ReportFinding', {k: finding[k] for k in ('finding_id', 'reported_number', 'text', 'sources')})
        with self.assertRaises(jsonschema.ValidationError):
            self.validate('ReportFinding', dict(finding, detection_result='uncontracted key'))


if __name__ == '__main__':
    unittest.main()
