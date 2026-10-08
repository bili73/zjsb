"""One deadline, serial recognition, and evidence-preserving partial results."""
from __future__ import annotations

import base64
import hashlib
import inspect
import re
import time
from collections.abc import Callable
from uuid import uuid4

from PIL import ImageOps

from .documents import DocumentError, decode_pages, normalized_box, png_bytes, region_task, split_regions
from .extraction import extract_result, issue


class _Stop(Exception):
    def __init__(self, code):
        self.code = code


class RecognitionFailure(RuntimeError):
    """A fatal supervisor failure must escape to the worker's fail-closed handler."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def process_document(content: bytes, doc_type: str, *, recognize: Callable, progress: Callable,
                     save_page: Callable, record_attempt: Callable, cancelled: Callable,
                     deadline: float, options: dict | None = None,
                     model_revisions: dict | None = None) -> dict:
    """Return a TaskResult payload plus pages/state/warnings; caller binds run IDs.

    Expected business errors return FAILED/CANCELLED and retained partial data.
    Storage/record/progress callback errors propagate: a failed durable write must
    not be represented as a successful or persisted result.
    """
    options = options or {}
    evidence, pages, warnings, limitations = [], [], [], []
    # Only coordinates and small metadata survive a page iteration, never PIL images.
    pending = {}
    stage, stop_code = 'PREPROCESSING', None
    medical = doc_type == 'MEDICAL_REPORT'
    model = 'paddleocr_vl' if medical else 'glm_ocr'
    alternate = 'glm_ocr' if medical else 'paddleocr_vl'
    attempt_models = (model, alternate) if medical else (model, model, alternate)
    generation_timeout = 20.0 if medical else None
    revisions = model_revisions if model_revisions is not None else {}
    cache = {}  # Successful predictions only; never shared with another Task or rerun.
    signature = inspect.signature(recognize)
    def accepts_keyword(name):
        parameter = signature.parameters.get(name)
        return (parameter is not None and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}) or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    accepts_context = accepts_keyword('context')
    accepts_generation_timeout = accepts_keyword('generation_timeout_seconds')

    def cache_key(used_model, task, prompt, input_hash, transform):
        revision = revisions.get(used_model)
        if not isinstance(revision, str) or not revision.strip():
            return None
        return (revision, used_model, task, prompt, input_hash, transform, 4096, generation_timeout)

    def check():
        if cancelled():
            raise _Stop('CANCELLED')
        if time.monotonic() >= deadline:
            raise _Stop('EXTRACT_TIMEOUT')

    def publish(next_stage, amount):
        nonlocal stage
        stage = next_stage
        check()
        progress(stage, amount, pages)
        check()

    try:
        publish('PREPROCESSING', 5)
        # Pass 1: read all reliable native content before spending time on OCR.
        # A slow logo on an early page must not hide later native report tables.
        for page in decode_pages(content, check):
            check()
            encoded_page = png_bytes(page.image)
            check()
            page_id = save_page(page.index, encoded_page, page.image.width, page.image.height)
            info = dict(page_id=page_id, page_index=page.index, width=page.image.width,
                        height=page.image.height, extraction_method='pending', regions=[])
            # Field.source IDs must resolve for native text just as they do for OCR.
            # No raw content belongs in page-region metadata.
            info['regions'].extend(
                {**{key: block[key] for key in ('region_id', 'bbox') if key in block},
                 'extraction_method': 'pdf_text', 'status': 'recognized'}
                for block in page.evidence)
            pages.append(info)
            evidence.extend(page.evidence)
            limitations.extend(page.limitations)
            warnings.extend(dict(code=code, message='PDF文字或布局需通过识别补充。') for code in page.warnings)
            regions = [region for box in page.ocr_boxes
                       for region in split_regions(page.image, box, doc_type == 'MEDICAL_REPORT')]
            planned = []
            for box in regions:
                region_id = str(uuid4())
                location = normalized_box(box, page.image.size)
                region = dict(region_id=region_id, bbox=location, extraction_method='ocr', status='pending')
                info['regions'].append(region)
                task = region_task(page.image, box, doc_type == 'MEDICAL_REPORT')
                planned.append((box, region, task))
            if planned:
                pending[page.index] = planned
            else:
                info['extraction_method'] = 'pdf_text'
            publish('PREPROCESSING', 10)
        page = None  # Do not retain the final full-page image while the second pass starts.
        encoded_page = None

        # Pass 2: decode one page at a time again, reusing first-pass IDs and boxes.
        # Native evidence and encrypted page saves are deliberately not repeated.
        for page in (decode_pages(content, check) if pending else []):
            if page.index not in pending:
                continue
            info = pages[page.index - 1]
            for box, region, task in pending[page.index]:
                publish('OCR', 20)
                region_id, location = region['region_id'], region['bbox']
                selected = None
                successful = False
                for attempt_index, used_model in enumerate(attempt_models):
                    check()
                    image = page.image.crop(box)
                    transform = 'original'
                    if attempt_index and not medical:
                        # A real deterministic input repair, recorded separately from inference.
                        image = ImageOps.autocontrast(image)
                        image = ImageOps.expand(image, border=24, fill='white')
                        transform = 'autocontrast_white_padding_24px'
                    image.thumbnail((1600, 1600))
                    png = png_bytes(image)
                    check()
                    started = time.monotonic()
                    input_hash = hashlib.sha256(png).hexdigest()
                    prompt = 'Table Recognition:' if task == 'table' else ('Text Recognition:' if used_model == 'glm_ocr' else 'OCR:')
                    key = cache_key(used_model, task, prompt, input_hash, transform)
                    cached = cache.get(key) if key is not None else None
                    attempt = dict(page_index=page.index, region_id=region_id, bbox=location,
                                   attempt=attempt_index + 1, model=used_model, task=task,
                                   input_sha256=input_hash, transform=transform, prompt=prompt,
                                   max_new_tokens=4096, generation_timeout_seconds=generation_timeout,
                                   cache_hit=cached is not None, inference_performed=cached is None,
                                   timeout_seconds=max(0., deadline - started))
                    fatal_error, timed_out = None, False
                    prediction, termination = {}, None
                    try:
                        if cached is not None:
                            prediction = dict(text=cached['text'], termination_reason='eos')
                            attempt.update(reused_from_region_id=cached['region_id'],
                                           reused_from_attempt=cached['attempt'])
                        else:
                            extra = {'context': dict(page=page.index, region_id=region_id, stage=stage)} if accepts_context else {}
                            if medical and accepts_generation_timeout:
                                extra['generation_timeout_seconds'] = generation_timeout
                            prediction = recognize(used_model, base64.b64encode(png).decode('ascii'),
                                                   task, max(.001, deadline - time.monotonic()), **extra)
                        if not isinstance(prediction, dict):
                            prediction = {'error_code': 'MODEL_OUTPUT_INVALID'}
                        if prediction.get('error_code') in {'SUPERVISION_FAILED', 'MODEL_REQUEST_TIMEOUT', 'EXTRACT_TIMEOUT'}:
                            raise RecognitionFailure(prediction['error_code'])
                        text = prediction.get('text')
                        # Reject explicit authentication secrets before recording model text.
                        if isinstance(text, str) and re.search(r'\b(?:CVV2?|CVC2?|CID)\s*[:：]?\s*\d{3,4}\b', text, re.I):
                            record_attempt({**attempt, 'status': 'rejected', 'error_code': 'UNSUPPORTED_DOC_TYPE',
                                            'elapsed_seconds': time.monotonic() - started})
                            raise _Stop('UNSUPPORTED_DOC_TYPE')
                        termination = prediction.get('termination_reason', prediction.get('termination'))
                        successful = isinstance(text, str) and bool(text.strip()) and not prediction.get('error_code') and termination not in {
                            'token_limit', 'length', 'repetition_stop', 'truncated', 'timeout', 'time_limit'}
                        if isinstance(text, str) and text.strip():
                            selected = dict(text=text, page=page.index, region_id=region_id,
                                            bbox=location, extraction_method='ocr')
                        attempt.update(prediction=prediction, status='completed' if successful else 'incomplete')
                    except _Stop:
                        raise
                    except Exception as exc:
                        code = getattr(exc, 'code', None)
                        fatal_error = exc if code == 'SUPERVISION_FAILED' else None
                        timed_out = code in {'MODEL_REQUEST_TIMEOUT', 'EXTRACT_TIMEOUT'}
                        # Only bounded codes cross the public record; exception strings can contain paths/PII.
                        allowed = {'RESOURCE_LIMIT', 'MODEL_PROCESS_EXITED', 'MODEL_LOAD_FAILED',
                                   'MODEL_WARMUP_FAILED', 'EXTRACT_TIMEOUT', 'INPUT_INVALID',
                                   'MODEL_REQUEST_TIMEOUT', 'SUPERVISION_FAILED'}
                        attempt.update(status='failed', error_code=code if code in allowed else 'MODEL_CALL_FAILED')
                    attempt['elapsed_seconds'] = time.monotonic() - started
                    record_attempt(attempt)
                    if fatal_error is not None:
                        raise fatal_error
                    if timed_out:
                        raise _Stop('EXTRACT_TIMEOUT')
                    # Persist text before budget/cancel check so completed partial work survives timeout.
                    if selected:
                        existing = next((i for i, block in enumerate(evidence) if block['region_id'] == region_id), None)
                        if existing is None:
                            evidence.append(selected)
                        else:
                            evidence[existing] = selected
                    region['status'] = 'recognized' if successful else 'incomplete'
                    check()
                    if successful:
                        # Revision may become known only after a cold worker load.
                        # A clipped actual generation configuration cannot populate
                        # the requested-settings key. Never cache cancelled work.
                        key = cache_key(used_model, task, prompt, input_hash, transform)
                        if (cached is None and key is not None and termination == 'eos'
                                and prediction.get('generation_timeout_seconds', generation_timeout) == generation_timeout
                                and prediction.get('max_new_tokens', 4096) == 4096):
                            cache[key] = dict(text=prediction['text'], region_id=region_id, attempt=attempt_index + 1)
                        break
                if not successful:
                    limitations.append(f'有识别区域在{len(attempt_models)}次尝试后仍不完整，保留最后一次可用原文。')
            info['extraction_method'] = 'mixed' if page.evidence else 'ocr'
            # Coordinate coverage is known; semantic OCR coverage remains unverified.
            limitations.append('自动分区保留整页像素覆盖；文字与表格行是否全部识别仍需原页复核。')
            del pending[page.index]
            publish('EXTRACTING', 70)
            if not pending:
                break
        publish('VALIDATING', 90)
    except _Stop as exc:
        stop_code = exc.code
    except DocumentError as exc:
        stop_code = {'DOCUMENT_LIMIT': 'FILE_TOO_LARGE', 'SENSITIVE_AUTH_DATA': 'UNSUPPORTED_DOC_TYPE',
                     'UNSUPPORTED_FORMAT': 'UNSUPPORTED_FORMAT'}.get(exc.code, 'DECODE_FAILED')
    if any(region['status'] == 'pending' for page_info in pages for region in page_info['regions']):
        limitations.append('仍有待OCR区域未处理；已读取的全部页文字及原生表格已保留，结果不代表完整识别。')
    result = extract_result(evidence, doc_type, complete=False)
    result['limitations'] = list(dict.fromkeys(result['limitations'] + limitations))
    if not stop_code:
        try:
            check()
        except _Stop as exc:
            stop_code = exc.code
    if limitations:
        result['review_issues'].append(issue('INCOMPLETE_OUTPUT', '识别覆盖尚未完成确认，请核对来源页。'))
    state = 'CANCELLED' if stop_code == 'CANCELLED' else 'FAILED' if stop_code else 'NEED_REVIEW'
    result.update(status=state, state=state, pages=pages, warnings=warnings)
    if stop_code:
        if stop_code != 'CANCELLED':
            result['error'] = dict(code=stop_code, message='文档处理未完成。', stage=stage)
    return result
