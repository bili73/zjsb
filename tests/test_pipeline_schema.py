"""Validate CPU pipeline payloads against the repository's actual OpenAPI schemas."""
import copy
import sys
import time
import unittest
from pathlib import Path
from uuid import uuid4

import jsonschema
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.documents import png_bytes
from ocr_app.extraction import extract_result
from ocr_app.pipeline import process_document


def json_schema(node):
    """OpenAPI 3.0 nullable -> equivalent JSON Schema union, without altering enums."""
    if isinstance(node, list):
        return [json_schema(value) for value in node]
    if not isinstance(node, dict):
        return node
    result = {key: json_schema(value) for key, value in node.items() if key != 'nullable'}
    if node.get('nullable') and isinstance(result.get('type'), str):
        result['type'] = [result['type'], 'null']
    return result


class PipelineSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json_schema(yaml.safe_load((ROOT / 'openapi.yaml').read_text(encoding='utf-8')))
        cls.image = png_bytes(Image.new('RGB', (100, 120), 'white'))

    def validate(self, name, instance):
        schema = dict(self.schema, **{'$ref': '#/components/schemas/' + name})
        jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).validate(instance)

    def publish_identity(self, payload):
        result = copy.deepcopy(payload)
        result.update(task_id=str(uuid4()), run_id=str(uuid4()), result_revision=1)
        result.setdefault('status', 'NEED_REVIEW')
        return result

    def pipeline(self, doc_type, text, **overrides):
        kwargs = dict(recognize=lambda *args, **extra: dict(text=text, termination_reason='eos'),
                      progress=lambda *args: None, save_page=lambda *args: str(uuid4()),
                      record_attempt=lambda value: None, cancelled=lambda: False,
                      deadline=time.monotonic() + 10)
        kwargs.update(overrides)
        return process_document(self.image, doc_type, **kwargs)

    def test_three_supported_templates_match_real_task_result_contract(self):
        texts = {
            'DIPLOMA': '姓名：测试员\n学校名称：测试大学\n专业：计算机\n学历层次：本科\n毕业日期：2026-06-30\n证书编号：000123',
            'DEGREE_CERT': '姓名：测试员\n学校名称：测试大学\n专业：计算机\n学位门类：学士\n授予日期：2026-06-30\n证书编号：000124',
            'MEDICAL_REPORT': '<table><tr><td>项目</td><td>结果</td><td>单位</td><td>参考范围</td></tr><tr><td>测试项目</td><td>1.00↓</td><td>mg/L</td><td>2-3</td></tr></table>',
        }
        for doc_type, text in texts.items():
            with self.subTest(doc_type=doc_type):
                result = self.pipeline(doc_type, text)
                self.validate('TaskResult', self.publish_identity(result))
                for page in result['pages']:
                    self.validate('Page', page)
                    if doc_type in {'DIPLOMA', 'DEGREE_CERT'}:
                        self.validate('ImagePreprocessing', page['image_preprocessing'])
                for item in result.get('items', []):
                    self.validate('MedicalItem', item)
                for field in result['fields']:
                    self.validate('Field', field)

    def test_missing_conflicting_and_unsupported_fields_still_match_schema(self):
        evidence = [dict(text=text, page=index, region_id=str(uuid4()), extraction_method='ocr', bbox=[0, 0, 1, 1])
                    for index, text in enumerate(['姓名：甲某', '姓名：乙某'], 1)]
        for doc_type in ['DIPLOMA', 'DEGREE_CERT', 'MEDICAL_REPORT', 'GENERIC']:
            result = extract_result(evidence, doc_type)
            self.validate('TaskResult', self.publish_identity(result))

    def test_bank_photocopy_conflict_sources_match_contract(self):
        evidence=[dict(text=text,_bank_role=role,page=1,region_id=str(uuid4()),extraction_method='ocr',bbox=[0,0,1,1])
                  for role,text in [('front','中国银行\n4111111111111111'),('supplement','4111111111111112\n李小明 13800000000\n东城支行')]]
        result=extract_result(evidence,'BANK_CARD')
        self.validate('TaskResult', self.publish_identity(result))

    def test_follow_up_summary_from_mixed_ocr_block_matches_contract(self):
        text = ('您共有2项异常需进一步检查并治疗：\n'
                '<table><tr><td>序号</td><td>项目</td><td>异常诊断</td></tr>'
                '<tr><td>1</td><td>合成项目甲</td><td>合成发现甲</td></tr>'
                '<tr><td>2</td><td>合成项目乙</td><td>合成发现乙</td></tr></table>')
        result = self.pipeline('MEDICAL_REPORT', text)
        summary = result['report_summary']
        self.assertEqual(summary['scope'], 'follow_up_required')
        self.assertEqual(summary['declared_count'], 2)
        self.assertEqual(len(summary['findings']), 2)
        self.assertEqual(summary['count_check'], 'unverified')
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertIsNone(result['stats']['total'])
        self.validate('TaskResult', self.publish_identity(result))
        self.validate('ReportSummary', summary)
        for finding in summary['findings']:
            self.validate('ReportFinding', finding)

    def test_timeout_and_cancel_status_match_contract(self):
        for options in [dict(deadline=time.monotonic() - 1), dict(cancelled=lambda: True)]:
            result = self.pipeline('MEDICAL_REPORT', 'fixture', **options)
            self.validate('TaskResult', self.publish_identity(result))
            if 'error' in result:
                self.validate('Error', result['error'])


if __name__ == '__main__':
    unittest.main()
