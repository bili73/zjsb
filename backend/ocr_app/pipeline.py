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
from .image_preprocessing import UPRIGHT_DOCUMENT_TYPES
from .doc_profiles import BANK_CARD_TYPES
from .certificate_recovery import RECOVERY_TYPES, missing_required_fields, locate_recovery_region, merge_recovery_fields


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
                     model_revisions: dict | None = None,
                     required_overrides: dict | None = None) -> dict:
    """Return a TaskResult payload plus pages/state/warnings; caller binds run IDs.

    Expected business errors return FAILED/CANCELLED and retained partial data.
    Storage/record/progress callback errors propagate: a failed durable write must
    not be represented as a successful or persisted result.
    """
    if doc_type == 'TABLE':
        from .photo_table_pipeline import process_photo_table
        return process_photo_table(content, recognize=recognize, progress=progress, save_page=save_page,
                                   record_attempt=record_attempt, cancelled=cancelled, deadline=deadline)
    options = options or {}
    evidence, pages, warnings, limitations = [], [], [], []
    # Only coordinates and small metadata survive a page iteration, never PIL images.
    pending = {}
    form_lines = {}
    bank_roles = {}
    recoveries = {}
    recovery_considered = False
    planning_complete = False
    stage, stop_code = 'PREPROCESSING', None
    preprocessing = {'doc_type': doc_type} if doc_type in UPRIGHT_DOCUMENT_TYPES else None
    bank_admission = options.get('bank_admission') if doc_type in BANK_CARD_TYPES else None
    if not isinstance(bank_admission, dict) or not bank_admission.get('text') or bank_admission.get('termination_reason') != 'eos':
        bank_admission = None
    medical = doc_type == 'MEDICAL_REPORT'
    generic = doc_type == 'GENERIC'
    interview = doc_type == 'INTERVIEW_FORM'
    paddle_primary = medical or generic or interview
    model = 'paddleocr_vl' if paddle_primary else 'glm_ocr'
    alternate = 'glm_ocr' if paddle_primary else 'paddleocr_vl'
    attempt_models = (model, alternate) if paddle_primary else (model, model, alternate)
    generation_timeout = 20.0 if medical or interview else 40.0 if generic or doc_type in BANK_CARD_TYPES else None
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

    def publish(next_stage):
        nonlocal stage
        stage = next_stage
        check()
        regions = [region for page_info in pages for region in page_info['regions']
                   if region['extraction_method'] == 'ocr']
        processed = sum(region['status'] in {'recognized', 'incomplete'} for region in regions)
        # Compatibility only: region work units, never elapsed-time/token estimates.
        amount = min(99, processed * 100 // len(regions)) if planning_complete and regions else 0
        progress(stage, amount, pages)
        check()

    def decoded_pages():
        if preprocessing is None:
            return decode_pages(content, check)
        return decode_pages(content, check, preprocessing=preprocessing)

    try:
        publish('PREPROCESSING')
        # Pass 1: read all reliable native content before spending time on OCR.
        # A slow logo on an early page must not hide later native report tables.
        for page in decoded_pages():
            check()
            encoded_page = png_bytes(page.image)
            check()
            page_id = save_page(page.index, encoded_page, page.image.width, page.image.height)
            info = dict(page_id=page_id, page_index=page.index, width=page.image.width,
                        height=page.image.height, extraction_method='pending', regions=[])
            if page.image_preprocessing is not None:
                info['image_preprocessing'] = dict(page.image_preprocessing)
                warning = page.image_preprocessing.get('warning')
                if warning:
                    warnings.append(dict(code=warning, message='图片自动摆正未能完全确认，请核对原图方向。'))
            # Field.source IDs must resolve for native text just as they do for OCR.
            # No raw content belongs in page-region metadata.
            info['regions'].extend(
                {**{key: block[key] for key in ('region_id', 'bbox') if key in block},
                 'extraction_method': 'pdf_text', 'status': 'recognized'}
                for block in page.evidence)
            pages.append(info)
            evidence.extend(page.evidence)
            reuse_bank_admission = bank_admission and not (page.image_preprocessing and any(
                page.image_preprocessing.get(key) for key in ('rotation_degrees', 'deskew_degrees')))
            if reuse_bank_admission:
                # Admission recognized the exact re-encoded crop before storage.
                # Changed preparation pixels require fresh recognition instead.
                region_id = str(uuid4())
                info['regions'].append(dict(region_id=region_id, bbox=[0., 0., 1., 1.],
                                             extraction_method='ocr', status='recognized'))
                evidence.append(dict(text=bank_admission['text'], page=page.index, region_id=region_id,
                                     bbox=[0., 0., 1., 1.], bbox_kind='region', extraction_method='ocr'))
                page.ocr_boxes = []
            limitations.extend(page.limitations)
            warnings.extend(dict(code=code, message='PDF文字或布局需通过识别补充。') for code in page.warnings)
            plans=[]
            for box in page.ocr_boxes:
                if interview:
                    from .interview_form import plan_interview_regions
                    regions, notes = plan_interview_regions(page.image, box, check)
                    plans.extend(regions); limitations.extend(notes)
                elif doc_type in BANK_CARD_TYPES:
                    from .bank_photocopy import plan_bank_regions
                    bank_plans, notes = plan_bank_regions(page.image, box, check)
                    plans.extend(bank_plans); limitations.extend(notes)
                elif generic:
                    from .generic_layout import plan_form_regions
                    form_regions, notes=plan_form_regions(page.image,box,check)
                    plans.extend(form_regions);limitations.extend(notes)
                else:
                    plans.extend(dict(box=area,task=region_task(page.image,area,medical))
                                 for area in split_regions(page.image,box,medical))
            planned = []
            for plan in plans:
                box=plan['box']
                region_id = str(uuid4())
                location = normalized_box(box, page.image.size)
                region = dict(region_id=region_id, bbox=location, extraction_method='ocr', status='pending')
                info['regions'].append(region)
                task = plan['task']
                if generic:form_lines[region_id]=plan['lines']
                if doc_type in BANK_CARD_TYPES:bank_roles[region_id]=plan.get('bank_role','whole')
                planned.append((box, region, task))
            if planned:
                pending[page.index] = planned
            else:
                info['extraction_method'] = 'ocr' if reuse_bank_admission else 'pdf_text'
            info['_preparation_complete'] = True
            publish('PREPROCESSING')
        planning_complete = True
        page = None  # Do not retain the final full-page image while the second pass starts.
        encoded_page = None

        # Pass 2: decode one page at a time again, reusing first-pass IDs and boxes.
        # Native evidence and encrypted page saves are deliberately not repeated.
        for page in (decoded_pages() if pending else []):
            if page.index not in pending:
                continue
            info = pages[page.index - 1]
            for box, region, task in pending[page.index]:
                publish('OCR')
                region_id, location = region['region_id'], region['bbox']
                recovering = region_id in recoveries
                soft_timeout = 20. if recovering else generation_timeout
                selected = None
                successful = False
                region_models = (model,) if recovering else (
                    (model, alternate) if bank_roles.get(region_id) in {'front','supplement','ambiguous_front'} else attempt_models)
                for attempt_index, used_model in enumerate(region_models):
                    check()
                    if interview:
                        selected = None
                    if interview and attempt_index:
                        task = 'ocr'  # Alternate text recognition retains out-of-cell handwriting.
                    image = page.image.crop(box)
                    transform = 'required_field_crop' if recovering else 'original'
                    if attempt_index and not paddle_primary:
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
                    key = None if recovering else cache_key(used_model, task, prompt, input_hash, transform)
                    cached = cache.get(key) if key is not None else None
                    attempt = dict(page_index=page.index, region_id=region_id, bbox=location,
                                   attempt=attempt_index + 1, model=used_model, task=task,
                                   input_sha256=input_hash, transform=transform, prompt=prompt,
                                   max_new_tokens=4096, generation_timeout_seconds=soft_timeout,
                                   cache_hit=cached is not None, inference_performed=cached is None,
                                   timeout_seconds=max(0., deadline - started))
                    if recovering:
                        attempt.update(recovery_fields=recoveries[region_id], recovery_reason='MISSING_REQUIRED_FIELDS')
                    if page.image_preprocessing is not None:
                        attempt['image_preprocessing'] = dict(page.image_preprocessing)
                    fatal_error, timed_out = None, False
                    prediction, termination = {}, None
                    try:
                        if cached is not None:
                            prediction = dict(text=cached['text'], termination_reason='eos')
                            attempt.update(reused_from_region_id=cached['region_id'],
                                           reused_from_attempt=cached['attempt'])
                        else:
                            extra = {'context': dict(page=page.index, region_id=region_id, stage=stage)} if accepts_context else {}
                            if soft_timeout is not None and accepts_generation_timeout:
                                extra['generation_timeout_seconds'] = soft_timeout
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
                        if (generic or interview or recovering) and termination != 'eos':successful=False
                        if isinstance(text, str) and text.strip():
                            selected = dict(text=text, page=page.index, region_id=region_id,
                                            bbox=location, extraction_method='ocr')
                            if doc_type in BANK_CARD_TYPES:selected['_bank_role']=bank_roles.get(region_id,'whole')
                            if interview:
                                from .interview_form import needs_alternate
                                selected['_interview_complete'] = successful
                                if attempt_index == 0 and successful and needs_alternate(selected):
                                    successful = False
                            if generic:
                                selected['_layout_lines']=form_lines.get(region_id,[])
                                if task == 'table' and successful:
                                    from .table_recognition import decode_table_output
                                    try:successful=not any(grid['warnings'] for grid in decode_table_output(text))
                                    except ValueError:successful=False
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
                    if timed_out and not recovering:
                        raise _Stop('EXTRACT_TIMEOUT')
                    # Persist text before budget/cancel check so completed partial work survives timeout.
                    if selected:
                        existing = None if interview else next((i for i, block in enumerate(evidence) if block['region_id'] == region_id), None)
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
                        key = None if recovering else cache_key(used_model, task, prompt, input_hash, transform)
                        if (cached is None and key is not None and termination == 'eos'
                                and prediction.get('generation_timeout_seconds', generation_timeout) == generation_timeout
                                and prediction.get('max_new_tokens', 4096) == 4096):
                            cache[key] = dict(text=prediction['text'], region_id=region_id, attempt=attempt_index + 1)
                        break
                if not successful:
                    limitations.append(f'有识别区域在{len(region_models)}次尝试后仍不完整，保留最后一次可用原文。')
                if (doc_type in RECOVERY_TYPES and len(pages) == 1 and successful and not recovering
                        and not recovery_considered and all(r['status'] != 'pending' for r in info['regions'])):
                    recovery_considered = True
                    missing = missing_required_fields(evidence, doc_type, required_overrides)
                    if missing:
                        plan = None
                        if deadline - time.monotonic() >= 5:
                            try:
                                plan = locate_recovery_region(page.image, doc_type, missing, check)
                            except Exception:
                                check()
                            check()
                        if plan:
                            recovery_id = str(uuid4())
                            retry = dict(region_id=recovery_id, bbox=normalized_box(plan['box'], page.image.size),
                                         extraction_method='ocr', status='pending')
                            info['regions'].append(retry)
                            recoveries[recovery_id] = plan['keys']
                            pending[page.index].append((plan['box'], retry, 'ocr'))
                            limitations.append('缺失必填字段触发一次局部补识别；仍缺失或有异议的字段请人工填写或核对。')
                        else:
                            limitations.append('缺失必填字段未能定位到可靠局部区域或剩余预算不足，请对照原件人工填写。')
                publish('OCR')
            info['extraction_method'] = 'mixed' if page.evidence else 'ocr'
            # Coordinate coverage is known; semantic OCR coverage remains unverified.
            limitations.append('保留整页原图对照；银行卡分区或整图识别的完整性需人工核对。' if doc_type in BANK_CARD_TYPES else
                               '已保留完整校正原图；主体内外文字及表格是否全部识别仍需核对。' if generic else
                               '自动分区保留整页像素覆盖；文字与表格行是否全部识别仍需原页复核。')
            del pending[page.index]
            if not pending:
                break
        publish('EXTRACTING')
    except _Stop as exc:
        stop_code = exc.code
    except DocumentError as exc:
        stop_code = {'DOCUMENT_LIMIT': 'FILE_TOO_LARGE', 'SENSITIVE_AUTH_DATA': 'UNSUPPORTED_DOC_TYPE',
                     'UNSUPPORTED_FORMAT': 'UNSUPPORTED_FORMAT'}.get(exc.code, 'DECODE_FAILED')
    if any(region['status'] == 'pending' for page_info in pages for region in page_info['regions']):
        limitations.append('仍有待OCR区域未处理；已读取的全部页文字及原生表格已保留，结果不代表完整识别。')
    result = extract_result(evidence, doc_type, complete=False)
    if recoveries:
        recognized_ids = {r['region_id'] for info in pages for r in info['regions']
                          if r['region_id'] in recoveries and r['status'] == 'recognized'}
        merge_recovery_fields(result, evidence, recoveries, recognized_ids)
    if doc_type in RECOVERY_TYPES and required_overrides is not None:
        from .required_fields import project_requirements
        project_requirements(result, required_overrides)
    if bank_admission:
        result['admission_seconds'] = bank_admission.get('elapsed_seconds')
    result['limitations'] = list(dict.fromkeys(result['limitations'] + limitations))
    if not stop_code:
        try:
            publish('VALIDATING')
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
