"""Mixed upload atomicity and content suggestions, without vision models."""
import io
import json
import unittest
from unittest.mock import patch
import fitz
from PIL import Image
from sqlalchemy import text
import test_business_api as base
import test_batch_ownership as ownership
from ocr_app.document_classification import content_types, suggestion, classify_file, _lock


class ClassificationTests(unittest.TestCase):
    def test_headers_disambiguate_adjacent_document_families(self):
        cases = {
            '姓名 张某 性别 男 民族 汉 住址 合成地址 公民身份号码 11010519491231002X': 'ID_CARD_FRONT',
            '中华人民共和国居民身份证 签发机关 测试公安局 有效期限 2020.01.01-长期': 'ID_CARD_BACK',
            '普通高等学校 毕业证书': 'DIPLOMA', '学士学位证书': 'DEGREE_CERT',
            '教育部学历证书电子注册备案表 学位证书 毕业证书': 'XUEXIN_DIPLOMA_TABLE',
            '健康体检报告': 'MEDICAL_REPORT', '营业执照 统一社会信用代码': 'BUSINESS_LICENSE',
            'PASSPORT 中华人民共和国护照': 'PASSPORT', '居民户口簿': 'HOUSEHOLD_REGISTER',
            '测试银行 6222 0000 1111 2222 333': 'BANK_CARD',
        }
        for value, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(suggestion(value, 'IMG_001.png')['doc_type'], expected)

    def test_uncertain_unsupported_and_mixed_are_never_guessed(self):
        for content, name in [('', '身份证.jpg'), ('', '身份证正反面.pdf'), ('', '学信网.pdf'), ('毕业证书 学士学位证书', '毕业证.pdf'),
                              ('教育部学籍在线验证报告', '学历证书电子注册备案表.pdf'), ('', '毕业证学位证.jpg')]:
            with self.subTest(content=content, name=name):
                self.assertIsNone(suggestion(content, name)['doc_type'])
        self.assertEqual(suggestion('学士学位证书', '毕业证.png')['doc_type'], 'DEGREE_CERT')
        self.assertEqual(suggestion('', '身份证国徽面.png')['basis'], 'filename')
        self.assertEqual(suggestion('无标题文字', 'IMG.png')['basis'], 'unknown')
        self.assertEqual(content_types('姓名 性别 民族 住址 公民身份号码 11010519491231002X 银行'), ({'ID_CARD_FRONT'}, False))

    def test_native_pdf_first_two_pages_and_no_plaintext_response(self):
        document = fitz.open()
        for title in ('普通高等学校毕业证书', '学士学位证书', '营业执照'):
            document.new_page().insert_text((40, 60), title, fontname='china-s')
        with patch('ocr_app.document_classification._ocr', side_effect=AssertionError('native text must suffice')):
            result = classify_file(document.tobytes(), 'IMG.pdf')
        self.assertIsNone(result['doc_type'])
        self.assertEqual(set(result['candidates']), {'DIPLOMA', 'DEGREE_CERT'})
        self.assertEqual(set(result), {'doc_type', 'basis', 'reason', 'candidates'})

    def test_busy_and_ocr_failure_allow_manual_choice(self):
        output = io.BytesIO(); Image.new('RGB', (100, 100)).save(output, format='PNG')
        _lock.acquire()
        try:
            self.assertIsNone(classify_file(output.getvalue(), 'IMG.png')['doc_type'])
        finally:
            _lock.release()
        with patch('ocr_app.document_classification._ocr', side_effect=RuntimeError('PII must not escape')):
            result = classify_file(output.getvalue(), '银行卡.png')
        self.assertEqual(result['basis'], 'filename')
        self.assertNotIn('PII', json.dumps(result))

    def test_xuexin_header_does_not_hide_a_different_second_page(self):
        document = fitz.open()
        for title in ('教育部学历证书电子注册备案表', '学士学位证书'):
            document.new_page().insert_text((40, 60), title, fontname='china-s')
        result = classify_file(document.tobytes(), 'IMG.pdf')
        self.assertIsNone(result['doc_type'])
        self.assertEqual(set(result['candidates']), {'XUEXIN_DIPLOMA_TABLE', 'DEGREE_CERT'})
        self.assertEqual(suggestion('七、本次体检项目意义', 'IMG.png')['doc_type'], 'MEDICAL_REPORT')


class MixedUploadTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp
    account = ownership.BatchOwnershipTests.account
    password = 'synthetic account password'

    def image_bytes(self, color):
        output = io.BytesIO(); Image.new('RGB', (300, 200), color).save(output, format='PNG')
        return output.getvalue()

    def post(self, headers, kinds, *, batch=None, data=None, files=None):
        fields = dict(file_types=json.dumps(kinds), abnormal_only='true')
        fields.update(dict(expected_revision='0') if batch else dict(person_name='合成人员'))
        fields.update(data or {})
        return self.client.post('/api/v1/batches' + ('/' + batch + '/append' if batch else ''), headers=headers,
            data=fields, files=files or [('files', ('same.png', self.image_bytes(color), 'image/png')) for color in ('red', 'blue')])

    def snapshot(self):
        with self.business.engine.connect() as c:
            rows = {table: c.execute(text('SELECT * FROM ' + table)).all() for table in ('batches', 'tasks', 'runs', 'artifacts', 'audit')}
        return rows, sorted(str(p) for p in self.business.storage.root.rglob('*.enc'))

    def test_mixed_order_repeated_names_and_medical_option(self):
        _, headers, _ = self.account('alice')
        response = self.post(headers, ['DIPLOMA', 'MEDICAL_REPORT'])
        self.assertEqual(response.status_code, 202, response.text)
        ids = response.json()['task_ids']
        tasks = [self.business.store.task(identifier) for identifier in ids]
        self.assertEqual([t['doc_type'] for t in tasks], ['DIPLOMA', 'MEDICAL_REPORT'])
        self.assertEqual([t['extract_options']['abnormal_only'] for t in tasks], [False, True])
        self.assertEqual([t['file_name'] for t in tasks], ['same.png', 'same.png'])
        self.assertEqual(self.business.store.batch(response.json()['batch_id'])['person_name'], '合成人员')

    def test_append_mixed_keeps_old_task_and_stale_request_atomic(self):
        _, headers, _ = self.account('alice')
        created = self.post(headers, ['ID_CARD_FRONT', 'DIPLOMA']).json()
        before = [self.business.store.task(identifier) for identifier in created['task_ids']]
        files = [('files', ('same.png', self.image_bytes(color), 'image/png')) for color in ('green', 'yellow')]
        response = self.post(headers, ['ID_CARD_BACK', 'DEGREE_CERT'], batch=created['batch_id'], files=files)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.business.store.batch(created['batch_id'])['id_card_pairing'], 'both_present')
        self.assertEqual([self.business.store.task(identifier) for identifier in created['task_ids']], before)
        state = self.snapshot()
        self.assertEqual(self.post(headers, ['ID_CARD_BACK', 'DEGREE_CERT'], batch=created['batch_id'], files=files).status_code, 409)
        self.assertEqual(self.snapshot(), state)

    def test_invalid_metadata_and_missing_person_create_nothing(self):
        _, headers, _ = self.account('alice')
        state = self.snapshot()
        for kinds, extra in [(['DIPLOMA'], {}), (['DIPLOMA', 'NOPE'], {}), (None, {}),
                             ('DIPLOMA', {}), (['DIPLOMA', 'DEGREE_CERT'], {'doc_type_hint': 'DIPLOMA'}),
                             (['DIPLOMA', 'DEGREE_CERT'], {'person_name': ''})]:
            with self.subTest(kinds=kinds, extra=extra):
                self.assertEqual(self.post(headers, kinds, data=extra).status_code, 422)
                self.assertEqual(self.snapshot(), state)

    def test_last_invalid_file_and_storage_failure_roll_back(self):
        _, headers, _ = self.account('alice')
        state = self.snapshot()
        response = self.post(headers, ['DIPLOMA', 'DEGREE_CERT'], files=[('files', ('ok.png', self.image, 'image/png')), ('files', ('bad.png', b'bad', 'image/png'))])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.snapshot(), state)
        original = self.business.storage.put
        calls = 0
        def fail_second(data):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('synthetic storage failure')
            return original(data)
        with patch.object(self.business.storage, 'put', side_effect=fail_second):
            self.assertEqual(self.post(headers, ['DIPLOMA', 'DEGREE_CERT']).status_code, 500)
        self.assertEqual(self.snapshot(), state)

    def test_duplicate_with_conflicting_types_rolls_back(self):
        _, headers, _ = self.account('alice')
        state = self.snapshot()
        files = [('files', ('same.png', self.image, 'image/png'))] * 2
        self.assertEqual(self.post(headers, ['DIPLOMA', 'DEGREE_CERT'], files=files).status_code, 422)
        self.assertEqual(self.snapshot(), state)
        response = self.post(headers, ['DIPLOMA', 'DIPLOMA'], files=files)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(response.json()['task_ids']), 1)

    def test_bank_pdf_rejects_the_whole_mixed_submission(self):
        _, headers, _ = self.account('alice')
        state = self.snapshot()
        document = fitz.open(); document.new_page()
        response = self.post(headers, ['DIPLOMA', 'BANK_CARD'], files=[
            ('files', ('first.png', self.image, 'image/png')),
            ('files', ('second.pdf', document.tobytes(), 'application/pdf'))])
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.snapshot(), state)

    def test_classification_is_authenticated_memory_only_and_independent_of_runtime(self):
        _, headers, _ = self.account('alice')
        state = self.snapshot()
        self.runtime.alive = False
        file = {'files': ('IMG.png', self.image, 'image/png')}
        self.assertEqual(self.client.post('/api/v1/classify', files=file).status_code, 401)
        with patch('ocr_app.document_classification._ocr', return_value='学士学位证书'):
            result = self.client.post('/api/v1/classify', headers=headers, files=file)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['doc_type'], 'DEGREE_CERT')
        self.assertEqual(self.snapshot(), state)
        _, viewer_headers, _ = self.account('viewer', 'viewer')
        self.assertEqual(self.client.post('/api/v1/classify', headers=viewer_headers, files=file).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/classify', headers=headers, files=list(file.items()) * 2).status_code, 413)
