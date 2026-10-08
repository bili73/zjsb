import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'backend')]
from schema_extraction import normalize, output_key, prompt, parse_prediction, score, templates
from ocr_app.extraction import DIPLOMA, DEGREE, MEDICAL, REQUIRED


class SchemaTests(unittest.TestCase):
    def test_spec_templates_match_current_keys_and_required_fields(self):
        for kind, dictionary in [('DIPLOMA', DIPLOMA), ('DEGREE_CERT', DEGREE), ('MEDICAL_REPORT', MEDICAL)]:
            fields = templates()[kind]
            self.assertEqual({f['key'] for f in fields}, set(dictionary))
            self.assertEqual({f['key'] for f in fields if f['required']}, REQUIRED[kind])

    def test_strict_parser_rejects_duplicate_unknown_keys_types_and_truncation(self):
        fields = [dict(key='age', type='int'), dict(key='name', type='string')]
        for text in ['{"age":1,"age":2,"name":"a"}', '{"age":true,"name":"a"}',
                     '{"age":"23","name":"a"}', '{"age":1}', '{"age":1,"name":"a","x":2}',
                     '{"age":NaN,"name":"a"}', 'explanation {"age":1,"name":"a"}']:
            self.assertIsNone(parse_prediction(text, fields)[0])
        self.assertIsNone(parse_prediction('{"age":1,"name":"a"}', fields, 'token_limit')[0])
        self.assertEqual(parse_prediction('```json\n{"age":23,"name":""}\n```', fields)[0], {'age':23, 'name':None})

    def test_date_precision_and_invalid_calendar_dates(self):
        self.assertEqual(normalize('issue_date', '二〇二六年六月十七日'), '2026-06-17')
        self.assertEqual(normalize('issue_date', '2026年6月'), '2026-06')
        self.assertNotEqual(normalize('issue_date', '2026-06'), normalize('issue_date', '2026-06-01'))
        self.assertTrue(normalize('issue_date', '2026-02-30').startswith('INVALID_DATE:'))

    def test_failed_predictions_remain_in_present_field_denominator(self):
        fields = [dict(key=k, required=True) for k in ['name', 'major', 'issue_date']]
        reference = {'name':dict(status='present',value='测试姓名'), 'major':dict(status='absent'),
                     'issue_date':dict(status='uncertain')}
        self.assertEqual([r['outcome'] for r in score(reference, None, fields)], ['missing','correct_absence','unscored'])
        self.assertEqual(score(reference, {'major':'猜测'}, fields)[1]['outcome'], 'false_positive')

    def test_chinese_template_uses_unique_keys_and_unambiguous_degree_level(self):
        fields = templates()['DEGREE_CERT']
        self.assertEqual(len({output_key(f,True) for f in fields}),len(fields))
        self.assertIn('"学位级别"',prompt(fields,True))

    def test_export_does_not_invent_memory_or_remove_failed_request_cost(self):
        from compare_schema_extraction import export
        rows = [dict(method='schema',doc_type='DIPLOMA',sample_id='fixture',parse_error='INVALID_JSON',
                     request_seconds=12,gpu_peak_allocated_gib=None,gpu_peak_reserved_gib=None,process_rss_peak_gib=None)]
        fields = [dict(method='schema',doc_type='DIPLOMA',required=True,reference_status='present',outcome='missing'),
                  dict(method='schema',doc_type='DIPLOMA',required=False,reference_status='uncertain',outcome='unscored')]
        with tempfile.TemporaryDirectory() as name:
            export(Path(name),rows,fields)
            group = json.loads((Path(name)/'summary.json').read_text(encoding='utf-8'))['groups'][0]
            self.assertEqual(group['present_fields'],1)
            self.assertEqual(group['field_accuracy'],0)
            self.assertEqual(group['total_request_seconds'],12)
            self.assertEqual(group['invalid_requests'],1)
            self.assertIsNone(group['process_rss_peak_gib'])


if __name__ == '__main__':
    unittest.main()
