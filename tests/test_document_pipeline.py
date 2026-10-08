import base64
import gc
import io
import sys
import time
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.documents import DocumentError, Page, decode_pages, png_bytes, region_task, split_regions, validate_document
from ocr_app.extraction import extract_result
from ocr_app.pipeline import process_document


TABLE = '''<table><tr><th>项目名称</th><th>英文缩写</th><th>结果</th><th>单位</th><th>参考区间</th></tr>
<tr><td>白细胞计数</td><td>WBC</td><td>11.20↑</td><td>10^9/L</td><td>3.5-9.5</td></tr>
<tr><td>检验项目乙</td><td>B</td><td>&gt;5.0</td><td>mg/L</td><td>0-4</td></tr>
<tr><td>定性项目</td><td>C</td><td>阳性</td><td></td><td></td></tr></table>'''


def block(text, page=1, region='9fd1a42b-95fd-4c78-b946-907f15b2093d'):
    return dict(text=text, page=page, region_id=region, extraction_method='ocr', bbox=[0, 0, 1, 1])


class DocumentTests(unittest.TestCase):
    def test_decoder_rejects_spoofed_and_encrypted_input(self):
        with self.assertRaises(DocumentError):
            validate_document(b'fake.png')
        doc = fitz.open()
        doc.new_page()
        data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='secret', owner_pw='owner')
        with self.assertRaises(DocumentError) as caught:
            validate_document(data)
        self.assertEqual(caught.exception.code, 'PDF_ENCRYPTED')

    def test_image_decode_and_limit(self):
        data = png_bytes(Image.new('RGB', (20, 30), 'white'))
        self.assertEqual(validate_document(data), 'image/png')
        pages = list(decode_pages(data))
        self.assertEqual(pages[0].image.size, (20, 30))
        self.assertEqual(pages[0].ocr_boxes, [(0, 0, 20, 30)])
        with patch('ocr_app.documents.MAX_PIXELS', 100):
            with self.assertRaises(DocumentError):
                validate_document(data)

    def test_pdf_text_is_used_without_ocr(self):
        doc = fitz.open()
        for i in range(2):
            page = doc.new_page()
            page.insert_text((50, 50), f'This is reliable text on PDF page {i + 1}.')
        pages = list(decode_pages(doc.tobytes()))
        self.assertEqual([p.index for p in pages], [1, 2])
        self.assertTrue(all(p.evidence and not p.ocr_boxes for p in pages))
        self.assertTrue(all(0 <= v <= 1 for p in pages for b in p.evidence for v in b['bbox']))

    def test_pdf_without_text_falls_back(self):
        doc = fitz.open()
        doc.new_page().draw_rect(fitz.Rect(40, 40, 400, 600), color=(0, 0, 0))
        page = next(decode_pages(doc.tobytes()))
        self.assertEqual(page.warnings, ['PDF_NO_TEXT_LAYER'])
        self.assertEqual(page.ocr_boxes, [(0, 0, *page.image.size)])

    def test_blank_pdf_has_no_useless_ocr(self):
        doc = fitz.open()
        doc.new_page()
        page = next(decode_pages(doc.tobytes()))
        self.assertEqual(page.ocr_boxes, [])
        self.assertEqual(page.evidence, [])

    def test_mixed_pdf_footer_does_not_replace_image_body(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 800), 'Footer only 001')
        body = Image.new('RGB', (300, 400), 'white')
        ImageDraw.Draw(body).text((20, 20), 'SCANNED BODY', fill='black')
        page.insert_image(fitz.Rect(40, 40, 400, 600), stream=png_bytes(body))
        decoded = next(decode_pages(doc.tobytes()))
        self.assertTrue(decoded.evidence)
        self.assertEqual(len(decoded.ocr_boxes), 1)
        self.assertLess(decoded.ocr_boxes[0][3], decoded.image.height)

    def test_ruled_table_is_explicit_table_task(self):
        image = Image.new('RGB', (500, 600), 'white')
        draw = ImageDraw.Draw(image)
        for y in range(20, 590, 50):
            draw.line((10, y, 490, y), fill='black', width=3)
        for x in [10, 150, 300, 490]:
            draw.line((x, 20, x, 570), fill='black', width=3)
        self.assertEqual(region_task(image, (0, 0, 500, 600), True), 'table')
        self.assertEqual(region_task(image, (0, 0, 500, 600), False), 'ocr')

    def test_split_has_full_coverage_and_only_whitespace_boundaries(self):
        image = Image.new('RGB', (1000, 4000), 'white')
        draw = ImageDraw.Draw(image)
        for y in range(100, 3900, 300):
            draw.rectangle((50, y, 950, y + 80), fill='black')
        boxes = split_regions(image, (0, 0, 1000, 4000), True)
        self.assertGreater(len(boxes), 1)
        self.assertEqual(boxes[0][1], 0)
        self.assertEqual(boxes[-1][3], 4000)
        for left, right in zip(boxes, boxes[1:]):
            self.assertEqual(left[3], right[1])
            self.assertEqual(image.getpixel((500, left[3])), (255, 255, 255))
        self.assertEqual(split_regions(image, (0, 0, 1000, 4000), False), [(0, 0, 1000, 4000)])


class ExtractionTests(unittest.TestCase):
    def test_table_column_assignment_and_precision(self):
        result = extract_result([block(TABLE)], 'MEDICAL_REPORT')
        first, bounded, positive = result['items']
        self.assertEqual(first['result_raw'], '11.20↑')
        self.assertEqual(first['reported_abnormal_marker'], '↑')
        self.assertEqual(first['abnormal_flag'], 'HIGH')
        self.assertEqual(first['unit'], '10^9/L')
        self.assertEqual(first['reference_range'], '3.5-9.5')
        self.assertEqual(first['alias'], 'WBC')
        self.assertIsNone(bounded['value_num'])
        self.assertEqual(bounded['result_raw'], '>5.0')
        self.assertEqual(positive['abnormal_flag'], 'POSITIVE')
        self.assertEqual(len(result['abnormal_summary']), 1)
        self.assertIsNone(result['stats']['total'])
        self.assertTrue(all(item['need_review'] and item['confidence'] is None for item in result['items']))

    def test_conflict_not_reference_or_first_candidate_selection(self):
        result = extract_result([block('姓名：甲某\n证书编号：00123'), block('姓名：乙某', page=2)], 'DIPLOMA')
        fields = {field['key']: field for field in result['fields']}
        self.assertIsNone(fields['name']['value'])
        self.assertEqual(fields['name']['review_reason'], 'CONFLICT')
        self.assertEqual(fields['certificate_no']['value'], '00123')
        self.assertEqual(fields['school_name']['review_reason'], 'MISSING')

    def test_medical_header_on_one_line(self):
        result = extract_result([block('姓名：测试员 性别：男 年龄：30岁 条码号：00042 检查日期：2026-09-30')], 'MEDICAL_REPORT')
        values = {key: field['value'] for key, field in result['basic_info'].items()}
        self.assertEqual(values['name'], '测试员')
        self.assertEqual(values['gender'], 'M')
        self.assertEqual(values['age'], 30)
        self.assertEqual(values['report_no'], '00042')

    def test_no_column_guess_without_headers(self):
        result = extract_result([block('<table><tr><td>WBC</td><td>9.0</td><td>3.5-9.5</td></tr></table>')], 'MEDICAL_REPORT')
        self.assertEqual(result['items'], [])
        self.assertIsNone(result['stats']['normal'])

    def test_repeated_item_names_are_not_overwritten(self):
        result = extract_result([block(TABLE), block(TABLE, page=2)], 'MEDICAL_REPORT')
        self.assertEqual(len(result['items']), 6)
        self.assertEqual(len({item['item_id'] for item in result['items']}), 6)

    def test_unsupported_type_remains_generic(self):
        result = extract_result([block('任意文字')], 'HOUSEHOLD_REGISTER')
        self.assertEqual(result['fields'], [])
        self.assertTrue(result['review_issues'])
        self.assertEqual(result['generic']['full_text'], '任意文字')

    def test_degree_major_is_required(self):
        result = extract_result([], 'DEGREE_CERT')
        major = next(field for field in result['fields'] if field['key'] == 'major')
        self.assertEqual(major['review_reason'], 'MISSING')


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.content = png_bytes(Image.new('RGB', (400, 500), 'white'))
        self.calls, self.attempts, self.pages, self.stages = [], [], [], []
        self.is_cancelled = False

    def run_pipeline(self, recognize=None, content=None, deadline=None, doc_type='MEDICAL_REPORT', **extra):
        def default(model, image, task, timeout):
            self.calls.append((model, task, timeout))
            with Image.open(io.BytesIO(base64.b64decode(image))) as decoded:
                self.assertLessEqual(max(decoded.size), 1600)
            return dict(text=TABLE, termination_reason='eos', output_tokens=100)
        def save(index, png, width, height):
            self.pages.append((index, png, width, height))
            return '9fd1a42b-95fd-4c78-b946-907f15b2093d'
        kwargs = dict(recognize=recognize or default, progress=lambda stage, value, pages: self.stages.append(stage),
                      save_page=save, record_attempt=self.attempts.append, cancelled=lambda: self.is_cancelled,
                      deadline=deadline if deadline is not None else time.monotonic() + 20)
        kwargs.update(extra)
        return process_document(content if content is not None else self.content, doc_type, **kwargs)

    def test_real_image_fake_model_and_review_contract(self):
        result = self.run_pipeline()
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertEqual(len(result['items']), 3)
        self.assertEqual(self.calls[0][:2], ('paddleocr_vl', 'ocr'))
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual(result['pages'][0]['extraction_method'], 'ocr')
        self.assertEqual(result['items'][0]['source']['bbox'], [0, 0, 1, 1])

    def test_certificate_truncated_attempts_keep_repair_then_fallback_policy(self):
        calls = []
        def recognize(model, image, task, timeout):
            calls.append((model, timeout, image))
            return dict(text=TABLE, termination_reason='token_limit')
        result = self.run_pipeline(recognize, doc_type='DIPLOMA')
        self.assertEqual([call[0] for call in calls], ['glm_ocr', 'glm_ocr', 'paddleocr_vl'])
        self.assertNotEqual(calls[0][2], calls[1][2])
        self.assertTrue(all(a[1] >= b[1] for a, b in zip(calls, calls[1:])))
        self.assertEqual(len(self.attempts), 3)
        self.assertEqual(result['pages'][0]['regions'][0]['status'], 'incomplete')

    def test_medical_soft_limit_uses_alternate_original_then_continues_next_page(self):
        calls = []
        def decoder(data, check):
            for index, color in [(1, 'white'), (2, 'gray')]:
                yield Page(index, Image.new('RGB', (100, 120), color), ocr_boxes=[(0, 0, 100, 120)])
        def recognize(model, image, task, timeout, **kwargs):
            calls.append((model, image, timeout, kwargs))
            return dict(text=TABLE, termination_reason='time_limit' if len(calls) <= 2 else 'eos')
        with patch('ocr_app.pipeline.decode_pages', side_effect=decoder):
            result = self.run_pipeline(recognize, deadline=time.monotonic() + 100)
        self.assertEqual([c[0] for c in calls], ['paddleocr_vl', 'glm_ocr', 'paddleocr_vl'])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertTrue(all(c[3]['generation_timeout_seconds'] == 20.0 and c[2] > 20 for c in calls))
        self.assertEqual([p['regions'][0]['status'] for p in result['pages']], ['incomplete', 'recognized'])
        self.assertEqual(result['status'], 'NEED_REVIEW')
        self.assertEqual(len(result['items']), 6)
        self.assertTrue(all(a['transform'] == 'original' for a in self.attempts))
        self.assertTrue(all(a['inference_performed'] and not a['cache_hit'] for a in self.attempts))

    @staticmethod
    def repeated_decoder(data, check):
        yield Page(1, Image.new('RGB', (100, 120), 'white'), ocr_boxes=[(0, 0, 100, 60)])
        yield Page(2, Image.new('RGB', (100, 120), 'white'), ocr_boxes=[(0, 60, 100, 120)])

    def test_cache_rebinds_source_and_does_not_copy_inference_metrics(self):
        revisions = {}  # Worker fills this same object during the first call.
        calls = []
        def recognize(model, *args, **kwargs):
            calls.append(model)
            revisions[model] = 'frozen-revision'
            return dict(text=TABLE, termination_reason='eos', recognition_seconds=2.5,
                        gpu_peak_allocated_gib=3, output_tokens=100)
        with patch('ocr_app.pipeline.decode_pages', side_effect=self.repeated_decoder):
            result = self.run_pipeline(recognize, model_revisions=revisions)
        self.assertEqual(calls, ['paddleocr_vl'])
        first, reused = self.attempts
        self.assertFalse(first['cache_hit'])
        self.assertTrue(reused['cache_hit'])
        self.assertFalse(reused['inference_performed'])
        self.assertEqual(reused['reused_from_region_id'], first['region_id'])
        self.assertEqual(reused['reused_from_attempt'], 1)
        self.assertEqual(set(reused['prediction']), {'text', 'termination_reason'})
        self.assertEqual(len(result['items']), 6)
        self.assertEqual(result['items'][0]['source']['bbox'], [0, 0, 1, .5])
        self.assertEqual(result['items'][3]['source']['bbox'], [0, .5, 1, 1])
        self.assertEqual(result['items'][3]['source']['page'], 2)
        self.assertEqual(result['items'][3]['source']['region_id'], reused['region_id'])
        self.assertNotEqual(first['region_id'], reused['region_id'])

    def test_cache_requires_known_revision_and_explicit_error_free_eos(self):
        predictions = [dict(text=TABLE), dict(text=TABLE, termination_reason='time_limit'),
                       dict(text=TABLE, termination_reason='token_limit'),
                       dict(text=TABLE, termination_reason='eos', error_code='MODEL_OUTPUT_INVALID'),
                       dict(text='', termination_reason='eos')]
        for prediction in predictions:
            with self.subTest(prediction=prediction):
                attempts, calls = [], []
                def recognize(model, *args, **kwargs):
                    calls.append(model)
                    return prediction
                with patch('ocr_app.pipeline.decode_pages', side_effect=self.repeated_decoder):
                    self.run_pipeline(recognize, model_revisions={'paddleocr_vl': 'p1', 'glm_ocr': 'g1'},
                                      record_attempt=attempts.append)
                self.assertGreaterEqual(len(calls), 2)
                self.assertFalse(any(a['cache_hit'] for a in attempts))
        with patch('ocr_app.pipeline.decode_pages', side_effect=self.repeated_decoder):
            self.run_pipeline()
        self.assertEqual(len(self.calls), 2)

    def test_cache_key_distinguishes_revision_task_pixels_and_actual_generation_settings(self):
        for difference in ['revision', 'task', 'pixels', 'generation', 'max_tokens']:
            with self.subTest(difference=difference):
                revisions = {'paddleocr_vl': 'p1'}
                calls, attempts = [], []
                def decoder(data, check):
                    yield Page(1, Image.new('RGB', (100, 120), 'white'), ocr_boxes=[(0, 0, 100, 120)])
                    color = 'gray' if difference == 'pixels' else 'white'
                    yield Page(2, Image.new('RGB', (100, 120), color), ocr_boxes=[(0, 0, 100, 120)])
                def recognize(model, *args, **kwargs):
                    calls.append(model)
                    prediction = dict(text=TABLE, termination_reason='eos')
                    if difference == 'generation':
                        prediction['generation_timeout_seconds'] = 5.0
                    if difference == 'max_tokens':
                        prediction['max_new_tokens'] = 512
                    return prediction
                def progress(stage, value, pages):
                    if difference == 'revision' and stage == 'EXTRACTING':
                        revisions['paddleocr_vl'] = 'p2'
                tasks = ['ocr', 'table'] if difference == 'task' else ['ocr', 'ocr']
                with patch('ocr_app.pipeline.decode_pages', side_effect=decoder), patch('ocr_app.pipeline.region_task', side_effect=tasks):
                    self.run_pipeline(recognize, model_revisions=revisions, progress=progress, record_attempt=attempts.append)
                self.assertEqual(len(calls), 2)
                self.assertFalse(any(a['cache_hit'] for a in attempts))

    def test_cache_does_not_cross_tasks_or_models(self):
        calls, attempts = [], []
        def recognize(model, *args, **kwargs):
            calls.append(model)
            return dict(text=TABLE, termination_reason='token_limit' if model == 'paddleocr_vl' else 'eos')
        revisions = {'paddleocr_vl': 'p1', 'glm_ocr': 'g1'}
        with patch('ocr_app.pipeline.decode_pages', side_effect=self.repeated_decoder):
            self.run_pipeline(recognize, model_revisions=revisions, record_attempt=attempts.append)
            self.run_pipeline(recognize, model_revisions=revisions, record_attempt=attempts.append)
        self.assertEqual(calls, ['paddleocr_vl', 'glm_ocr', 'paddleocr_vl'] * 2)
        self.assertEqual(sum(a['cache_hit'] for a in attempts), 2)
        self.assertTrue(all(a['model'] == 'glm_ocr' for a in attempts if a['cache_hit']))

    def test_cancel_and_hard_timeout_do_not_continue_to_cached_or_alternate_region(self):
        for reason in ['cancel', 'hard_timeout']:
            with self.subTest(reason=reason):
                calls, attempts = [], []
                self.is_cancelled = False
                class Failure(RuntimeError):
                    code = 'MODEL_REQUEST_TIMEOUT'
                def recognize(model, *args, **kwargs):
                    calls.append(model)
                    if reason == 'hard_timeout':
                        raise Failure()
                    self.is_cancelled = True
                    return dict(text=TABLE, termination_reason='eos')
                with patch('ocr_app.pipeline.decode_pages', side_effect=self.repeated_decoder):
                    result = self.run_pipeline(recognize, model_revisions={'paddleocr_vl': 'p1'},
                                               record_attempt=attempts.append)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result['status'], 'CANCELLED' if reason == 'cancel' else 'FAILED')
                self.assertEqual(result['pages'][1]['regions'][0]['status'], 'pending')

    def test_timeout_keeps_finished_attempt_and_partial_result(self):
        def recognize(*args):
            time.sleep(.06)
            return dict(text=TABLE, termination_reason='eos')
        result = self.run_pipeline(recognize, deadline=time.monotonic() + .04)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertEqual(len(result['items']), 3)
        self.assertEqual(len(self.attempts), 1)

    def test_cancel_keeps_finished_attempt(self):
        def recognize(*args):
            self.is_cancelled = True
            return dict(text=TABLE, termination_reason='eos')
        result = self.run_pipeline(recognize)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(len(result['items']), 3)

    def test_budget_and_cancellation_prevent_first_call(self):
        result = self.run_pipeline(deadline=time.monotonic() - 1)
        self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertEqual(self.calls, [])
        self.is_cancelled = True
        self.assertEqual(self.run_pipeline()['status'], 'CANCELLED')

    def test_pdf_text_only_never_calls_model(self):
        doc = fitz.open()
        doc.new_page().insert_text((50, 50), 'Reliable native PDF text without raster images.')
        result = self.run_pipeline(content=doc.tobytes())
        self.assertEqual(self.calls, [])
        self.assertEqual(result['pages'][0]['extraction_method'], 'pdf_text')

    def test_decoder_error_and_storage_failure(self):
        result = self.run_pipeline(content=b'broken PDF')
        self.assertEqual(result['error']['code'], 'DECODE_FAILED')
        def failing_store(*args):
            raise OSError('controlled fixture')
        with self.assertRaises(OSError):
            self.run_pipeline(save_page=failing_store)

    def test_supervision_failure_propagates_and_is_never_retried(self):
        class Failure(RuntimeError):
            code = 'SUPERVISION_FAILED'
        def recognize(*args):
            raise Failure()
        with self.assertRaises(Failure):
            self.run_pipeline(recognize)
        self.assertEqual(len(self.attempts), 1)

    def test_model_timeout_stops_without_retry(self):
        class Failure(RuntimeError):
            code = 'MODEL_REQUEST_TIMEOUT'
        def recognize(*args):
            raise Failure()
        result = self.run_pipeline(recognize)
        self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertEqual(len(self.attempts), 1)

    def test_context_goes_to_supporting_callback(self):
        contexts = []
        def recognize(*args, **kwargs):
            contexts.append(kwargs['context'])
            return dict(text=TABLE, termination_reason='eos')
        self.run_pipeline(recognize)
        self.assertEqual(contexts[0]['page'], 1)
        self.assertEqual(contexts[0]['stage'], 'OCR')
        self.assertIn('region_id', contexts[0])

    def test_authentication_secret_is_not_recorded_or_published(self):
        def recognize(*args):
            return dict(text='CVV: 123', termination_reason='eos')
        result = self.run_pipeline(recognize)
        self.assertEqual(result['error']['code'], 'UNSUPPORTED_DOC_TYPE')
        self.assertNotIn('123', str(result))
        self.assertNotIn('123', str(self.attempts))

    def test_parse_time_counts_against_task_budget(self):
        original = extract_result
        def slow(*args, **kwargs):
            time.sleep(.06)
            return original(*args, **kwargs)
        with patch('ocr_app.pipeline.extract_result', side_effect=slow):
            result = self.run_pipeline(deadline=time.monotonic() + .04)
        self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')

    def test_first_page_ocr_timeout_retains_later_pdf_native_text_and_all_page_ids(self):
        doc = fitz.open()
        doc.new_page().draw_rect(fitz.Rect(40, 40, 400, 600), color=(0, 0, 0))
        doc.new_page().insert_text((50, 50), 'LATER_PAGE_NATIVE_CONTENT survives the earlier OCR timeout.')
        doc.new_page().draw_rect(fitz.Rect(40, 40, 400, 600), color=(0, 0, 0))
        saved = []
        def save(index, png, width, height):
            saved.append(index)
            return f'page-{index}'
        class Failure(RuntimeError):
            code = 'MODEL_REQUEST_TIMEOUT'
        def recognize(*args):
            self.assertEqual(saved, [1, 2, 3])
            raise Failure()
        result = self.run_pipeline(recognize, content=doc.tobytes(), save_page=save)
        self.assertEqual(result['error']['code'], 'EXTRACT_TIMEOUT')
        self.assertIn('LATER_PAGE_NATIVE_CONTENT', result['generic']['full_text'])
        self.assertEqual(saved, [1, 2, 3])
        self.assertEqual([page['page_id'] for page in result['pages']], ['page-1', 'page-2', 'page-3'])
        self.assertEqual(result['pages'][2]['regions'][0]['status'], 'pending')
        self.assertTrue(any('待OCR' in text for text in result['limitations']))

    def test_second_pass_never_duplicates_native_table_items_or_saved_pages(self):
        passes = []
        def decoder(data, check):
            passes.append(True)
            yield Page(1, Image.new('RGB', (100, 120), 'white'), ocr_boxes=[(0, 0, 100, 120)])
            native = {**block(TABLE, page=2), 'extraction_method': 'pdf_text'}
            yield Page(2, Image.new('RGB', (100, 120), 'white'), evidence=[native], ocr_boxes=[(0, 0, 100, 120)])
        with patch('ocr_app.pipeline.decode_pages', side_effect=decoder):
            result = self.run_pipeline(recognize=lambda *args: dict(text='OCR footer only', termination_reason='eos'))
        self.assertEqual(len(passes), 2)
        self.assertEqual([page[0] for page in self.pages], [1, 2])
        self.assertEqual(len(result['items']), 3)
        self.assertTrue(all(item['source']['page'] == 2 for item in result['items']))

    def test_two_passes_keep_constant_number_of_live_full_page_images(self):
        refs, live_counts = [], []
        def decoder(data, check):
            for index in range(1, 13):
                check()
                image = Image.new('RGB', (100, 120), 'white')
                refs.append(weakref.ref(image))
                gc.collect()
                live_counts.append(sum(reference() is not None for reference in refs))
                yield Page(index, image, ocr_boxes=[(0, 0, 100, 120)])
        with patch('ocr_app.pipeline.decode_pages', side_effect=decoder):
            result = self.run_pipeline(recognize=lambda *args: dict(text='OCR fixture', termination_reason='eos'))
        self.assertEqual(len(result['pages']), 12)
        self.assertEqual(len(refs), 24)
        self.assertLessEqual(max(live_counts), 2)
        gc.collect()
        self.assertTrue(all(reference() is None for reference in refs))

    def test_native_and_ocr_source_ids_resolve_to_distinct_page_regions(self):
        class Failure(RuntimeError):
            code = 'MODEL_REQUEST_TIMEOUT'
        def decoder(data, check):
            native = [dict(text=text, page=1, region_id=str(uuid4()),
                           extraction_method='pdf_text', bbox=[0, 0, 1, .8])
                      for text in ['姓名：测试员', TABLE]]
            yield Page(1, Image.new('RGB', (100, 120), 'white'), evidence=native,
                       ocr_boxes=[(0, 100, 100, 120)])
        for timeout in [False, True]:
            def recognize(*args):
                if timeout:
                    raise Failure()
                return dict(text=TABLE, termination_reason='eos')
            with self.subTest(timeout=timeout), patch('ocr_app.pipeline.decode_pages', side_effect=decoder):
                result = self.run_pipeline(recognize)
            regions = {(page['page_index'], region['region_id']): region
                       for page in result['pages'] for region in page['regions']}
            for field in result['fields'] + result['items']:
                if 'source' not in field:
                    continue
                src = field['source']
                region = regions[(src['page'], src['region_id'])]
                self.assertEqual(region['bbox'], src['bbox'])
                self.assertEqual(region['extraction_method'], src['extraction_method'])
            native_regions = [r for r in regions.values() if r['extraction_method'] == 'pdf_text']
            self.assertEqual(len(native_regions), 2)
            self.assertTrue(all(r['status'] == 'recognized' for r in native_regions))
            if timeout:
                self.assertEqual(sum(r['status'] == 'pending' for r in regions.values()), 1)
                self.assertTrue(all(r['extraction_method'] == 'ocr' for r in regions.values() if r['status'] == 'pending'))


if __name__ == '__main__':
    unittest.main()
