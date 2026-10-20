"""Missing certificate fields get one bounded source-backed supplemental attempt."""
import base64
from copy import deepcopy
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.documents import Page, png_bytes
from ocr_app.pipeline import process_document, RecognitionFailure


PRIMARY = ('姓名：测试甲\n校名：示例大学\n在本校\n专业，学习，修完全部课程。\n'
           '学历层次：专科\n毕业日期：2020年6月\n证书编号：000123')
SUPPLEMENT = '在本校测试工程专业学习。\n姓名：测试乙\n校名：另一大学'
LINES = [dict(text='在本校', box=[100, 280, 350, 315]),
         dict(text='测试工程', box=[700, 280, 900, 315]),
         dict(text='专业，学习，修完全部课程', box=[100, 335, 600, 370])]


def indexed(result):
    return {field['key']: field for field in result['fields']}


class CertificateRecoveryPipelineTests(unittest.TestCase):
    def run_case(self, primary=PRIMARY, supplemental=SUPPLEMENT, termination='eos', *,
                 kind='DIPLOMA', count=1, native=False, lines=LINES, recovery_error=None,
                 cancel_recovery=False, layout_error=None, **extra):
        self.calls, self.attempts, self.progress, self.cancelled = [], [], [], False
        def decode(data, check, **kwargs):
            for index in range(1, count + 1):
                image = Image.new('RGB', (1000, 800), 'white')
                evidence = [dict(text=primary, page=index, region_id='native', extraction_method='pdf_text')] if native else []
                yield Page(index, image, evidence=evidence, ocr_boxes=[] if native else [(0, 0, 1000, 800)])
        def recognize(model, payload, task, timeout, **kwargs):
            with Image.open(io.BytesIO(base64.b64decode(payload))) as image:
                self.calls.append(dict(model=model, size=image.size, timeout=timeout, **kwargs))
            if len(self.calls) > count and kind in {'DIPLOMA', 'DEGREE_CERT'}:
                if recovery_error:
                    raise recovery_error
                if cancel_recovery:
                    self.cancelled = True
                return dict(text=supplemental, termination_reason=termination)
            return dict(text=primary, termination_reason='eos')
        with patch('ocr_app.pipeline.decode_pages', side_effect=decode), \
                patch('ocr_app.table_recognition.nearby_text', return_value=deepcopy(lines), side_effect=layout_error) as locate:
            result = process_document(b'fixture', kind, recognize=recognize,
                progress=lambda stage, value, pages: self.progress.append((stage, value, deepcopy(pages))),
                save_page=lambda *args: 'saved-page', record_attempt=self.attempts.append,
                cancelled=lambda: self.cancelled, deadline=time.monotonic() + 60, **extra)
            self.locator_calls = locate.call_count
        return result

    def test_missing_major_after_eos_gets_one_local_retry_without_changing_filled_fields(self):
        result = self.run_case()
        fields = indexed(result)
        self.assertEqual(fields['major']['value'], '测试工程')
        self.assertEqual([c['model'] for c in self.calls], ['glm_ocr', 'glm_ocr'])
        self.assertEqual(self.locator_calls, 1)
        self.assertLess(self.calls[1]['size'][1], self.calls[0]['size'][1])
        self.assertLessEqual(self.calls[1]['size'][0] / self.calls[1]['size'][1], 2.3)
        self.assertEqual(self.calls[1]['generation_timeout_seconds'], 20.)
        self.assertLessEqual(self.calls[1]['timeout'], self.calls[0]['timeout'])
        for key, value in [('name', '测试甲'), ('school_name', '示例大学'), ('certificate_no', '000123')]:
            self.assertEqual(fields[key]['value'], value)
        self.assertIsNone(fields['major']['confidence'])
        self.assertTrue(fields['major']['need_review'])
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertTrue(result['generic']['full_text'].startswith(PRIMARY))
        self.assertIn(SUPPLEMENT, result['generic']['full_text'])
        regions = result['pages'][0]['regions']
        self.assertEqual(len(regions), 2)
        self.assertEqual(fields['major']['source']['region_id'], regions[1]['region_id'])
        self.assertEqual(fields['major']['source']['bbox'], regions[1]['bbox'])
        self.assertNotEqual(regions[1]['bbox'], [0, 0, 1, 1])
        values = [value for _, value, _ in self.progress]
        self.assertEqual(values, sorted(values))

    def test_unchanged_missing_field_does_not_loop_or_fill_from_truncated_output(self):
        for text, termination in [('在本校\n专业，学习。', 'eos'),
                                  ('在本校测试工程专业学习。', 'time_limit')]:
            with self.subTest(termination=termination):
                result = self.run_case(supplemental=text, termination=termination)
                self.assertEqual(len(self.calls), 2)
                self.assertIsNone(indexed(result)['major']['value'])
                self.assertEqual(result['status'], 'NEED_REVIEW')
                self.assertIn(text, result['generic']['full_text'])

    def test_recovery_conflicts_stay_candidates(self):
        result = self.run_case(supplemental='在本校测试甲专业学习。\n在本校测试乙专业学习。')
        major = indexed(result)['major']
        self.assertIsNone(major['value'])
        self.assertEqual({c['value'] for c in major['candidates']}, {'测试甲', '测试乙'})
        self.assertEqual(len(self.calls), 2)

    def test_complete_or_conflicting_primary_does_not_trigger_recovery(self):
        for major in ['在本校测试工程专业学习。', '在本校测试甲专业学习。\n在本校测试乙专业学习。']:
            with self.subTest(major=major):
                result = self.run_case(primary=PRIMARY.replace('在本校\n专业，学习，修完全部课程。', major))
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.locator_calls, 0)

    def test_configured_optional_major_does_not_trigger_recovery(self):
        result = self.run_case(required_overrides={'DIPLOMA': ['name', 'school_name', 'education_level', 'graduate_date', 'certificate_no']})
        self.assertIsNone(indexed(result)['major']['value'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.locator_calls, 0)

    def test_configured_required_birth_date_uses_its_label(self):
        lines = [dict(text='出生日期', box=[100, 100, 300, 135]),
                 dict(text='1990年1月', box=[400, 100, 650, 135])]
        result = self.run_case(lines=lines, required_overrides={'DIPLOMA': ['birth_date']},
                               supplemental='出生日期：1990年1月')
        self.assertEqual(indexed(result)['birth_date']['value'], '1990-01')
        self.assertIsNone(indexed(result)['major']['value'])
        self.assertEqual(len(self.calls), 2)

    def test_no_geometry_native_multi_page_and_medical_keep_manual_path(self):
        for kwargs in [dict(lines=[]), dict(native=True), dict(count=2), dict(kind='MEDICAL_REPORT')]:
            with self.subTest(kwargs=kwargs):
                result = self.run_case(**kwargs)
                self.assertEqual(result['status'], 'NEED_REVIEW')
                if kwargs.get('kind') != 'MEDICAL_REPORT':
                    self.assertIsNone(indexed(result)['major']['value'])
                    self.assertFalse(any(c['model'] == 'paddleocr_vl' for c in self.calls))
                    self.assertEqual(len(self.calls), 0 if kwargs.get('native') else kwargs.get('count', 1))

    def test_failed_retry_preserves_primary_and_does_not_loop(self):
        result = self.run_case(recovery_error=ValueError('synthetic failure'))
        self.assertIsNone(indexed(result)['major']['value'])
        self.assertEqual(indexed(result)['school_name']['value'], '示例大学')
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertEqual(len(self.calls), 2)

    def test_degree_uses_the_same_recovery_and_keeps_primary_school(self):
        primary = PRIMARY + '\n学位级别：学士\n学位授予日期：2020年7月'
        result = self.run_case(kind='DEGREE_CERT', primary=primary)
        self.assertEqual(indexed(result)['major']['value'], '测试工程')
        self.assertEqual(indexed(result)['school_name']['value'], '示例大学')
        self.assertEqual(len(self.calls), 2)

    def test_layout_failure_and_recovery_timeout_preserve_manual_path(self):
        result = self.run_case(layout_error=ValueError('synthetic missing asset'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertIsNone(indexed(result)['major']['value'])
        result = self.run_case(recovery_error=RecognitionFailure('MODEL_REQUEST_TIMEOUT'))
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertIsNone(indexed(result)['major']['value'])
        self.assertEqual(len(self.calls), 2)

    def test_cancelled_retry_and_fatal_supervision_keep_existing_terminal_rules(self):
        result = self.run_case(cancel_recovery=True)
        self.assertEqual(result['status'], 'CANCELLED')
        with self.assertRaises(RecognitionFailure):
            self.run_case(recovery_error=RecognitionFailure('SUPERVISION_FAILED'))


if __name__ == '__main__':
    unittest.main()
