"""Durable task transitions. The worker never holds a transaction during OCR."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid
from time import monotonic

from sqlalchemy import bindparam, text

from .extraction import confirmed_abnormal, medical_exclusion_reason, medical_statistics

ACTIVE = {'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'}
TERMINAL = {'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'}
from .doc_profiles import SUPPORTED, LABELS


def now():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return str(uuid.uuid4())


class TaskError(Exception):
    def __init__(self, code, message, status=409, details=None):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status
        self.details = details


def upload_types(doc_type, count):
    kinds = [doc_type] * count if isinstance(doc_type, str) else doc_type
    if not isinstance(kinds, list) or not kinds or len(kinds) != count:
        raise TaskError('INVALID_REQUEST', '每个文件必须按顺序指定一种材料类型', 422)
    if any(not isinstance(kind, str) or kind not in SUPPORTED for kind in kinds):
        raise TaskError('UNSUPPORTED_DOC_TYPE', '材料类型未受支持，请从材料目录选择', 422)
    return kinds


def _phone_patterns(result):
    """Only recognized mainland mobile values/candidates authorize text masking."""
    numbers = set()
    fields = [field for field in result.get('fields', []) if field.get('key') == 'phone']
    fields.append(result.get('basic_info', {}).get('phone', {}))
    for field in fields:
        for value in [field.get('value'), *(candidate.get('value') for candidate in field.get('candidates', []))]:
            if not isinstance(value, str):
                continue
            compact = re.sub(r'[\s()（）-]', '', value)
            match = re.fullmatch(r'(?:\+?86)?(1[3-9][0-9]{9})', compact)
            if match:
                numbers.add(match[1])
    separator = r'[\s()（）-]*'
    return [(re.compile(r'(?<![0-9])[（(]?(?:\+?86' + separator + r')?' + separator.join(number) + r'[）)]?(?![0-9])'),
             '****' + number[-4:]) for number in sorted(numbers)]


def mask_text(value, phone_patterns=()):
    if not isinstance(value, str):
        return value
    for pattern, replacement in phone_patterns:
        value = pattern.sub(replacement, value)
    value = re.sub(r'(?<!\d)\d{17}[\dXx](?!\d)', lambda m: m[0][:3] + '*' * 11 + m[0][-4:], value)
    value = re.sub(r'(?<!\d)(?:\d{13,19}|(?:\d{4}[ -]){3}\d{1,4}(?:[ -]\d{1,3})?)(?!\d)',
                   lambda m: '****' + re.sub(r'\D', '', m[0])[-4:], value)
    return value


def masked(value, phone_patterns=()):
    if isinstance(value, dict):
        # Business values are masked; validated structural identities must stay
        # round-trippable even when a UUID happens to contain mostly digits.
        return {k: v if isinstance(v, str) and (
            k.endswith('_id') and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', v)
            or k == 'error_id' and re.fullmatch(r'e_[0-9a-f]{32}', v)
            or (k in {'sha256', 'content_hash'} or k.endswith(('_hash', '_sha256'))) and re.fullmatch(r'[0-9a-fA-F]{64}', v)
        ) else masked(v, phone_patterns) for k, v in value.items()}
    if isinstance(value, list):
        return [masked(v, phone_patterns) for v in value]
    return mask_text(value, phone_patterns)


def public_result(value, required_overrides=None):
    """Authenticated internal responses retain full values, never private helpers."""
    def strip_private(item):
        if isinstance(item, dict):
            return {key: strip_private(val) for key, val in item.items()
                    if not key.startswith('_') and key != 'value_masked'}
        if isinstance(item, list):
            return [strip_private(val) for val in item]
        return item
    projected = strip_private(value)
    if isinstance(projected, dict) and projected.get('doc_type') == 'BANK_CARD':
        projected['fields'] = [field for field in projected.get('fields', [])
                               if field.get('key') != 'card_number_masked']
    if (isinstance(projected, dict) and projected.get('doc_type') == 'MEDICAL_REPORT'
            and ('fields' in projected or 'basic_info' in projected)):
        from .doc_profiles import profile
        from .extraction import _field
        fields = dict(projected.get('basic_info', {}))
        fields.update({field['key']: field for field in projected.get('fields', [])})
        current = []
        for meta in profile('MEDICAL_REPORT'):
            field = fields.get(meta['key']) or _field(meta['key'], meta['label'], [], meta['required'])
            field.update(required=meta['required'], editable=meta['editable'])
            current.append(field)
        projected.update(fields=current, basic_info={field['key']:field for field in current})
        from .medical_ledger import refresh_ledger
        refresh_ledger(projected)
        for key in ('items', 'abnormal_summary'):
            for item in projected.get(key, []):
                exclusion = medical_exclusion_reason(item.get('name'))
                if exclusion or 'abnormal_exclusion_reason' in item:
                    item['abnormal_exclusion_reason'] = exclusion
                if exclusion:
                    item['need_review'] = False
        if 'abnormal_summary' in projected:
            projected['abnormal_summary'] = [item for item in projected['abnormal_summary'] if not item.get('abnormal_exclusion_reason')]
        if (any(item.get('abnormal_exclusion_reason') for item in projected.get('items', []))
                and projected.get('stats', {}).get('total') is not None):
            projected['stats'] = medical_statistics(projected['items'])
    if required_overrides is not None and isinstance(projected, dict):
        from .required_fields import project_requirements
        project_requirements(projected, required_overrides)
    return projected


class TaskStore:
    def __init__(self, engine, storage, logger=None):
        self.engine, self.storage, self.logger = engine, storage, logger

    def required_policy(self, connection=None):
        from .required_fields import load_policy
        if connection is not None:
            return load_policy(connection)
        with self.engine.connect() as current:
            return load_policy(current)

    @contextmanager
    def transaction(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            yield connection

    def _batch_row(self, connection, batch_id, user=None):
        row = connection.execute(text('SELECT * FROM batches WHERE id=:id'), {'id': batch_id}).mappings().first()
        if row is None or (user is not None and user['role'] != 'admin'
                           and (row['owner_id'] is None or row['owner_id'] != user['user_id'])):
            raise TaskError('INVALID_REQUEST', '任务或批次不存在或无权访问', 404)
        return row

    def _row(self, connection, task_id, user=None):
        row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().first()
        if row is None:
            raise TaskError('INVALID_REQUEST', '任务或批次不存在或无权访问', 404)
        if user is not None:
            self._batch_row(connection, row['batch_id'], user)
        return dict(row)

    @staticmethod
    def _owner_filter(user):
        # None is reserved for trusted internal workers, never HTTP callers.
        return dict(unrestricted=user is None or user['role'] == 'admin',
                    owner=user['user_id'] if user else None)

    def _owner(self, connection, batch):
        account = connection.execute(text('SELECT username,display_name FROM web_users WHERE id=:id'),
                                     {'id': batch['owner_id']}).mappings().first()
        saved = self.storage.unpack(batch['owner_snapshot_enc'], {})
        return dict(user_id=batch['owner_id'], username=account['username'] if account else saved.get('username'),
                    display_name=account['display_name'] if account else saved.get('display_name'),
                    account_exists=account is not None)

    def _audit(self, connection, event, actor='worker', task=None, **details):
        connection.execute(text('INSERT INTO audit VALUES (:id,:actor,:task,:run,:event,:at,:detail)'),
                           dict(id=identity(), actor=actor, task=task['id'] if task else None,
                                run=task['run_id'] if task else None, event=event, at=now(),
                                detail=json.dumps(details)))

    def create_batch(self, files, doc_type, actor, options=None, *, person_name=None, authorize=None):
        return self._write_upload(files, doc_type, actor, options, person_name=person_name, authorize=authorize)

    def append_batch(self, batch_id, files, doc_type, expected_revision, actor, options=None, *, user, authorize):
        return self._write_upload(files, doc_type, actor, options, batch_id=batch_id,
                                  expected_revision=expected_revision, user=user, authorize=authorize)

    def _write_upload(self, files, doc_type, actor, options=None, *, person_name=None,
                      batch_id=None, expected_revision=None, user=None, authorize=None):
        kinds = upload_types(doc_type, len(files))
        if person_name is not None:
            if not isinstance(person_name, str) or not 1 <= len(person_name.strip()) <= 80 or not person_name.isprintable():
                raise TaskError('INVALID_REQUEST', '人员名称需1至80个可打印字符，不能全为空白', 422)
            person_name = person_name.strip()
        for file, kind in zip(files, kinds):
            if kind == 'BANK_CARD':
                if file.get('mime') not in {'image/png', 'image/jpeg', 'image/heic', 'image/heif'} or file.get('actual_source_page_count') != 1:
                    raise TaskError('UNSUPPORTED_FORMAT', '银行卡请上传已解码的单张照片', 415)
        batch, created, references, task_ids = batch_id or identity(), now(), [], []
        try:
            with self.transaction() as connection:
                if authorize:
                    authorize(connection)
                if batch_id:
                    row = self._batch_row(connection, batch_id, user)
                    if not row['is_person_package']:
                        raise TaskError('INVALID_REQUEST', '旧批次未指定人员，请新建人员材料包后追加', 422)
                    if type(expected_revision) is not int or row['package_revision'] != expected_revision:
                        raise TaskError('RESULT_VERSION_CONFLICT', '材料包已更新，请刷新后重新确认追加', 409)
                    connection.execute(text('UPDATE batches SET package_revision=package_revision+1 WHERE id=:id'), {'id': batch})
                else:
                    account = connection.execute(text('SELECT username,display_name FROM web_users WHERE id=:id'),
                                             {'id': actor}).mappings().first()
                    connection.execute(text('INSERT INTO batches(id,created_at,name_enc,owner_id,owner_snapshot_enc,person_name_enc,is_person_package) '
                                        'VALUES (:id,:at,:name,:owner,:snapshot,:person,:package)'),
                                   dict(id=batch, at=created, name=self.storage.pack(LABELS[kinds[0]]),
                                        owner=actor, snapshot=self.storage.pack(dict(account)) if account else None,
                                        person=self.storage.pack(person_name) if person_name else None,
                                        package=int(isinstance(doc_type, list) or person_name is not None)))
                hashes = dict(connection.execute(text('SELECT content_hash,id FROM tasks WHERE batch_id=:id'), {'id': batch}).all())
                for file, kind in zip(files, kinds):
                    digest = file.get('content_hash') or hashlib.sha256(file['data']).hexdigest()
                    if digest in hashes:
                        duplicate = self._row(connection, hashes[digest])
                        if duplicate['doc_type'] != kind:
                            raise TaskError('INVALID_REQUEST', '相同文件已按其他材料类型上传，请核对原文件与所选类型', 422)
                        warnings = self.storage.unpack(duplicate['warnings_enc'], [])
                        warnings.append(dict(code='DUPLICATE_FILE', message='同批次重复文件已复用任务'))
                        connection.execute(text('UPDATE tasks SET warnings_enc=:value WHERE id=:id'),
                                           dict(value=self.storage.pack(warnings), id=duplicate['id']))
                        continue
                    task_id, run_id = identity(), identity()
                    reference = self.storage.put(file['data'])
                    references.append(reference)
                    duplicate = connection.execute(text('SELECT t.id FROM tasks t JOIN batches b ON b.id=t.batch_id '
                                                        'WHERE t.content_hash=:hash AND b.owner_id=:owner LIMIT 1'),
                                                   {'hash': digest, 'owner': actor}).first()
                    warnings = [dict(code='DUPLICATE_FILE', message='其他批次存在相同文件，本批次独立处理')] if duplicate else []
                    params = dict(id=task_id, batch=batch, run=run_id, at=created,
                                  expires=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                                  hash=digest, doc=kind, reference=reference,
                                  meta=self.storage.pack(dict(file_name=file['name'], file_size=len(file['data']), mime_type=file['mime'],
                                      actual_source_page_count=file.get('actual_source_page_count'), processed_content_hash=file.get('processed_content_hash'))),
                                  options=self.storage.pack(dict(options or {}, abnormal_only=kind == 'MEDICAL_REPORT' and bool((options or {}).get('abnormal_only')),
                                      **({'bank_admission': file['admission']} if file.get('admission') else {}))), warnings=self.storage.pack(warnings))
                    connection.execute(text('''INSERT INTO tasks
                        (id,batch_id,run_id,status,created_at,updated_at,expires_at,content_hash,doc_type,input_ref,meta_enc,options_enc,warnings_enc)
                        VALUES (:id,:batch,:run,'QUEUED',:at,:at,:expires,:hash,:doc,:reference,:meta,:options,:warnings)'''), params)
                    connection.execute(text("INSERT INTO runs(id,task_id,status) VALUES (:run,:id,'QUEUED')"), params)
                    connection.execute(text("INSERT INTO artifacts(id,task_id,run_id,kind,reference) VALUES (:aid,:id,:run,'input',:reference)"),
                                       dict(params, aid=identity()))
                    self._audit(connection, 'task_created', actor, dict(id=task_id, run_id=run_id))
                    task_ids.append(task_id)
                    hashes[digest] = task_id
                if batch_id:
                    self._audit(connection, 'package_appended', actor, batch_id=batch, added_tasks=len(task_ids))
            return dict(batch_id=batch, task_ids=task_ids)
        except BaseException:
            for reference in references:
                self.storage.delete(reference)
            raise

    def confirm_person(self, batch_id, person_name, expected_revision, actor, *, user, authorize):
        if not isinstance(person_name, str) or not 1 <= len(person_name.strip()) <= 80 or not person_name.isprintable():
            raise TaskError('INVALID_REQUEST', '人员名称需1至80个可打印字符，不能全为空白', 422)
        with self.transaction() as connection:
            authorize(connection)
            row = self._batch_row(connection, batch_id, user)
            if not row['is_person_package']:
                raise TaskError('INVALID_REQUEST', '当前批次不是人员材料包', 422)
            if type(expected_revision) is not int or row['package_revision'] != expected_revision:
                raise TaskError('RESULT_VERSION_CONFLICT', '材料包已更新，请刷新后重新确认姓名', 409)
            connection.execute(text('UPDATE batches SET person_name_enc=:name,package_revision=package_revision+1 WHERE id=:id'),
                               dict(id=batch_id, name=self.storage.pack(person_name.strip())))
            self._audit(connection, 'package_person_confirmed', actor, batch_id=batch_id)
        return self.batch(batch_id, user=user)

    def _public(self, row, policy=None):
        from .exporting import required_export_blockers
        policy = policy if policy is not None else self.required_policy()
        pages = self.storage.unpack(row['pages_enc'], [])
        meta = self.storage.unpack(row['meta_enc'])
        total_pages = meta.get('actual_source_page_count')
        if type(total_pages) is not int or total_pages <= 0:
            total_pages = None
        regions = [region for page in pages for region in page.get('regions', [])
                   if region.get('extraction_method') == 'ocr']
        recognized = sum(region.get('status') == 'recognized' for region in regions)
        incomplete = sum(region.get('status') == 'incomplete' for region in regions)
        plan_known = (total_pages is not None and len(pages) == total_pages
                      and all(page.get('_preparation_complete') is True for page in pages))
        progress_detail = dict(stage=row['status'], prepared_pages=len(pages), total_pages=total_pages,
                               processed_regions=recognized + incomplete, recognized_regions=recognized,
                               incomplete_regions=incomplete, total_regions=len(regions) if plan_known else None)
        export_blockers = required_export_blockers(self.storage.unpack(row['result_enc']), policy['overrides'])
        return public_result(dict(task_id=row['id'], batch_id=row['batch_id'], run_id=row['run_id'],
                           result_revision=row['revision'], cancel_requested=bool(row['cancel_requested']),
                           status=row['status'], progress=row['progress'], progress_detail=progress_detail, doc_type=row['doc_type'],
                           doc_type_confidence=None, doc_type_confidence_method='unavailable',
                           page_count=len(pages), pages=pages, content_hash=row['content_hash'],
                           created_at=row['created_at'], updated_at=row['updated_at'], expires_at=row['expires_at'],
                           error=json.loads(row['error_json']) if row['error_json'] else None,
                           warnings=self.storage.unpack(row['warnings_enc'], []), summary=None,
                           export_ready=not export_blockers, export_blockers=export_blockers,
                           required_fields_revision=policy['revision'],
                           need_review_fields=[], extract_options={k: v for k, v in self.storage.unpack(row['options_enc'], {}).items() if k != 'bank_admission'},
                           **meta))

    def task(self, task_id, *, user=None):
        with self.engine.connect() as connection:
            return self._public(self._row(connection, task_id, user), self.required_policy(connection))

    def tasks(self, batch_id=None, status=None, *, policy=None, user=None):
        with self.engine.connect() as connection:
            if batch_id is not None and user is not None:
                self._batch_row(connection, batch_id, user)
            policy = policy if policy is not None else self.required_policy(connection)
            rows = connection.execute(text('SELECT t.* FROM tasks t JOIN batches b ON b.id=t.batch_id '
                                           'WHERE (:batch IS NULL OR t.batch_id=:batch) '
                                           'AND (:status IS NULL OR t.status=:status) '
                                           'AND (:unrestricted=1 OR b.owner_id=:owner) ORDER BY t.created_at,t.id'),
                                      dict(batch=batch_id, status=status, **self._owner_filter(user))).mappings()
            return [self._public(row, policy) for row in rows]

    def batch(self, batch_id, *, policy=None, user=None):
        with self.engine.connect() as connection:
            row = dict(self._batch_row(connection, batch_id, user))
            owner = self._owner(connection, row)
        policy = policy if policy is not None else self.required_policy()
        tasks = self.tasks(batch_id, policy=policy, user=user)
        with self.engine.connect() as connection:
            row = self._batch_row(connection, batch_id, user)
            suggestions = []
            if row['is_person_package']:
                from .person_packages import name_suggestions
                results = []
                for task in connection.execute(text('SELECT id,doc_type,result_enc,meta_enc FROM tasks WHERE batch_id=:id'),
                                               {'id': batch_id}).mappings():
                    result = self.storage.unpack(task['result_enc'])
                    if result:
                        results.append(dict(result, task_id=task['id'], doc_type=task['doc_type'],
                                            _source_filename=self.storage.unpack(task['meta_enc']).get('file_name')))
                suggestions = name_suggestions(results)
            counts = {state: sum(t['status'] == state for t in tasks) for state in TERMINAL | ACTIVE | {'QUEUED', 'NEED_REVIEW'}}
            if any(t['status'] not in TERMINAL for t in tasks) or not tasks:
                state = 'PROCESSING'
            elif counts['COMPLETED'] == len(tasks):
                state = 'COMPLETED'
            elif counts['CANCELLED'] == len(tasks):
                state = 'CANCELLED'
            else:
                state = 'PARTIAL' if counts['COMPLETED'] else 'FAILED'
            kinds = sorted({t.get('doc_type') for t in tasks if t.get('doc_type')},
                           key=lambda kind: list(LABELS).index(kind) if kind in LABELS else len(LABELS))
            labels = [LABELS.get(kind, '待确定类型') for kind in kinds]
            display_name = ('混合材料 · ' + ' / '.join(labels)) if len(labels) > 1 else labels[0] if labels else '待确定类型'
            person_name = self.storage.unpack(row['person_name_enc']) if row['person_name_enc'] is not None else None
            sides = set(kinds) & {'ID_CARD_FRONT', 'ID_CARD_BACK'}
            pairing = ('unassigned' if not row['is_person_package'] else 'both_present' if len(sides) == 2
                       else 'missing_back' if 'ID_CARD_FRONT' in sides else 'missing_front' if sides else 'not_provided')
            warnings = ([dict(code='MISSING_ID_FRONT', message='缺少身份证人像面，请核对人员归属后补充上传')]
                        if pairing == 'missing_front' else [])
            if person_name:
                display_name = person_name + ' · ' + display_name
            elif row['is_person_package']:
                display_name = '人员材料包·姓名待确认 · ' + display_name
            if len(suggestions) > 1 or person_name and any(s['name'] != person_name for s in suggestions):
                warnings.append(dict(code='PERSON_NAME_CONFLICT', message='识别姓名存在差异，请对照来源文件核对归属；系统不会自动移动材料'))
            return dict(batch_id=batch_id, name=display_name, display_name=display_name, owner=owner,
                        person_name=person_name, is_person_package=bool(row['is_person_package']), name_suggestions=suggestions,
                        package_revision=row['package_revision'], id_card_pairing=pairing,
                        required_fields_revision=policy['revision'],
                        status=state, task_count=len(tasks), file_count=len(tasks), total_count=len(tasks), completed_count=counts['COMPLETED'],
                        failed_count=counts['FAILED'], cancelled_count=counts['CANCELLED'], rejected_count=counts['REJECTED'],
                        need_review_count=counts['NEED_REVIEW'], created_at=row['created_at'],
                        expires_at=min((t['expires_at'] for t in tasks), default=None),
                        updated_at=max((t['updated_at'] for t in tasks), default=row['created_at']), warnings=warnings)

    def batches(self, page=1, page_size=20, date_from=None, date_to=None, *, user=None):
        if date_from and date_to and date_from>date_to:
            raise TaskError('INVALID_REQUEST', '开始日期不能晚于结束日期', 422)
        zone = timezone(timedelta(hours=8))
        try:
            start = datetime.combine(date_from, datetime.min.time(), zone).astimezone(timezone.utc).isoformat() if date_from else None
            end = datetime.combine(date_to+timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc).isoformat() if date_to else None
        except (ValueError, OverflowError):
            raise TaskError('INVALID_REQUEST', '日期超出支持范围', 422) from None
        with self.engine.connect() as connection:
            policy = self.required_policy(connection)
            ids = connection.execute(text('SELECT id FROM batches WHERE (:start IS NULL OR created_at>=:start) '
                'AND (:end IS NULL OR created_at<:end) AND (:unrestricted=1 OR owner_id=:owner) '
                'ORDER BY created_at DESC,id'),dict(start=start,end=end,**self._owner_filter(user))).scalars().all()
        return dict(items=[self.batch(i, policy=policy, user=user) for i in ids[(page-1)*page_size:page*page_size]],
                    total=len(ids), page=page, page_size=page_size)

    def result(self, task_id, items_filter=None, include_normal_summary=True, *, user=None):
        from .exporting import required_export_blockers
        with self.engine.connect() as connection:
            policy = self.required_policy(connection)
            row = self._row(connection, task_id, user)
            result = self.storage.unpack(row['result_enc'])
            if result is None:
                raise TaskError('INVALID_STATE', '当前任务尚无可用识别结果')
            export_blockers = required_export_blockers(result, policy['overrides'])
            result.update(export_ready=not export_blockers, export_blockers=export_blockers)
            result.update(task_id=task_id, run_id=row['run_id'], result_revision=row['revision'], status=row['status'])
            if result.get('doc_type') == 'DIPLOMA':
                # Public profile only: retain encrypted history and original evidence.
                result['fields'] = [field for field in result.get('fields', [])
                                    if field.get('key') not in {'principal', 'study_mode'}]
            result['required_fields_revision'] = policy['revision']
            result = public_result(result, policy['overrides'])
            options = self.storage.unpack(row['options_enc'], {})
            if result.get('doc_type') == 'MEDICAL_REPORT':
                selected = items_filter or ('flagged' if options.get('abnormal_only') else 'all')
                def abnormal(item):
                    return confirmed_abnormal(item)
                def unknown(item):
                    return not item.get('abnormal_exclusion_reason') and (item.get('abnormal_flag') == 'UNKNOWN' or (item.get('abnormal_flag') == 'POSITIVE' and not abnormal(item)))
                if selected == 'flagged':
                    result['items'] = [i for i in result.get('items', []) if abnormal(i) or unknown(i)]
                elif selected == 'abnormal':
                    result['items'] = [i for i in result.get('items', []) if abnormal(i)]
                elif selected == 'unknown':
                    result['items'] = [i for i in result.get('items', []) if unknown(i)]
                if not include_normal_summary:
                    result['normal_summary'] = None
            return result

    def queue_depth(self):
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT COUNT(*) FROM tasks WHERE status='QUEUED' AND cancel_requested=0")).scalar_one()

    def claim_next(self, doc_types=None):
        allowed = tuple(SUPPORTED if doc_types is None else doc_types)
        if not allowed:
            return None
        if not set(allowed) <= SUPPORTED:
            raise ValueError('Unsupported document lane')
        with self.transaction() as connection:
            query = text("""SELECT * FROM tasks WHERE status='QUEUED' AND cancel_requested=0
                AND stop_code IS NULL AND doc_type IN :allowed ORDER BY created_at,id LIMIT 1""").bindparams(
                    bindparam('allowed', expanding=True))
            row = connection.execute(query, {'allowed': allowed}).mappings().first()
            if row is None:
                return None
            row = dict(row)
            timestamp = now()
            connection.execute(text("UPDATE tasks SET status='PREPROCESSING',active_started_at=:at,updated_at=:at WHERE id=:id"),
                               dict(at=timestamp, id=row['id']))
            connection.execute(text("UPDATE runs SET status='PREPROCESSING',started_at=:at WHERE id=:id"),
                               dict(at=timestamp, id=row['run_id']))
            self._audit(connection, 'task_claimed', task=row)
            row.update(status='PREPROCESSING', active_started_at=timestamp, updated_at=timestamp)
            return row

    def cancelled(self, task_id, run_id):
        with self.engine.connect() as connection:
            row = self._row(connection, task_id)
            return row['run_id'] != run_id or bool(row['cancel_requested']) or bool(row['stop_code']) or row['status'] not in ACTIVE

    def progress(self, task, stage, progress, pages=None):
        if stage not in ACTIVE:
            raise ValueError('Invalid task stage')
        with self.transaction() as connection:
            row = self._row(connection, task['id'])
            if row['run_id'] != task['run_id'] or row['status'] not in ACTIVE or row['cancel_requested'] or row['stop_code']:
                return False
            connection.execute(text('UPDATE tasks SET status=:stage,progress=:progress,pages_enc=:pages,updated_at=:at WHERE id=:id'),
                               dict(stage=stage, progress=max(0, min(99, int(progress))), id=task['id'], at=now(),
                                    pages=self.storage.pack(pages) if pages is not None else row['pages_enc']))
            return True

    def save_page(self, task, index, data, width, height):
        reference, page_id = self.storage.put(data), identity()
        try:
            with self.transaction() as connection:
                row = self._row(connection, task['id'])
                if row['run_id'] != task['run_id'] or row['cancel_requested'] or row['status'] not in ACTIVE or row['stop_code']:
                    raise TaskError('INVALID_STATE', '任务已停止')
                connection.execute(text('''INSERT INTO artifacts
                    (id,task_id,run_id,kind,page_index,width,height,reference) VALUES
                    (:id,:task,:run,'corrected',:page,:width,:height,:reference)'''),
                                   dict(id=page_id, task=task['id'], run=task['run_id'], page=index,
                                        width=width, height=height, reference=reference))
            return page_id
        except BaseException:
            self.storage.delete(reference)
            raise

    def attempt(self, task, payload):
        with self.transaction() as connection:
            connection.execute(text('INSERT INTO attempts VALUES (:id,:task,:run,:at,:payload)'),
                               dict(id=identity(), task=task['id'], run=task['run_id'], at=now(), payload=self.storage.pack(payload)))

    def publish(self, task, result):
        with self.transaction() as connection:
            row = self._row(connection, task['id'])
            status = result.get('status', result.get('state', 'NEED_REVIEW'))
            if status not in TERMINAL | {'NEED_REVIEW'}:
                raise ValueError('Invalid result status')
            # History may record an obsolete run, but only the current uncancelled version publishes.
            error = result.get('error')
            error_json = json.dumps(error, ensure_ascii=False) if error else None
            if row['run_id'] != task['run_id'] or row['status'] not in ACTIVE or row['stop_code']:
                return False
            if row['cancel_requested']:
                status = 'CANCELLED'
            elif row['revision'] != task['revision']:
                return False
            payload = self.storage.pack(dict(result, status=status))
            # A cancellation acknowledgement wins over a late computation. Preserve
            # history for audit, but never publish the post-cancellation result.
            current_payload = row['result_enc'] if row['cancel_requested'] else payload
            current_pages = row['pages_enc'] if row['cancel_requested'] else self.storage.pack(result.get('pages', []))
            connection.execute(text('UPDATE runs SET status=:status,ended_at=:at,result_enc=:result,error_json=:error WHERE id=:id'),
                               dict(status=status, at=now(), result=payload, error=error_json, id=task['run_id']))
            connection.execute(text('''UPDATE tasks SET status=:status,progress=:progress,result_enc=:result,pages_enc=:pages,
                error_json=:error,warnings_enc=:warnings,revision=revision+1,updated_at=:at WHERE id=:id'''),
                               dict(status=status, progress=100 if status in {'NEED_REVIEW', 'COMPLETED'} else row['progress'],
                                    result=current_payload, pages=current_pages,
                                    error=error_json, warnings=self.storage.pack(self.storage.unpack(row['warnings_enc'], []) + result.get('warnings', [])),
                                    at=now(), id=task['id']))
            self._audit(connection, 'task_' + status.lower(), task=row)
            return True

    def _expected(self, row, run_id, revision):
        if row['run_id'] != run_id or row['revision'] != revision:
            raise TaskError('RESULT_VERSION_CONFLICT', '任务版本已变化，请刷新后再操作')

    def _access_history(self, connection, row, actor, event, reason, **details):
        """Reasons can contain private text: keep them encrypted, not audit JSON."""
        payload = dict(event=event, actor=actor, reason=reason, at=now(),
                       run_id=row['run_id'], result_revision=row['revision'], **details)
        reference = self.storage.put(json.dumps(payload, ensure_ascii=False).encode())
        try:
            connection.execute(text('INSERT INTO artifacts(id,task_id,run_id,kind,reference) VALUES (:id,:task,:run,:kind,:ref)'),
                               dict(id=identity(), task=row['id'], run=row['run_id'], kind='access_history', ref=reference))
        except BaseException:
            self.storage.delete(reference)
            raise

    def review(self, task_id, body, actor, *, user=None, authorize=None):
        from .review import apply_review, invalid, reason
        reference = None
        try:
            with self.transaction() as connection:
                if authorize:
                    authorize(connection)
                row = self._row(connection, task_id, user)
                self._expected(row, body.get('run_id'), body.get('expected_revision'))
                if row['status'] not in {'FAILED', 'NEED_REVIEW', 'COMPLETED'}:
                    raise TaskError('INVALID_STATE', '当前任务不能进行人工复核')
                original = self.storage.unpack(row['result_enc'])
                pages = self.storage.unpack(row['pages_enc'], [])
                if original is None:
                    if row['status'] != 'FAILED':
                        raise TaskError('INVALID_STATE', '当前任务无可用结果')
                    from .extraction import extract_result
                    original = extract_result([], row['doc_type'])
                    original.update(pages=pages, review_issues=original.get('review_issues', []))
                coverage = body.get('coverage')
                verified = False
                if coverage is not None or row['status'] == 'FAILED':
                    meta = self.storage.unpack(row['meta_enc'], {})
                    count = meta.get('actual_source_page_count')
                    if count is None:
                        # Legacy tasks predate total-page metadata. Decode only;
                        # never infer coverage from the processed-page prefix.
                        from .business import validate_upload
                        checked = validate_upload(self.storage.read(row['input_ref']), meta.get('file_name', 'source.pdf'))
                        count = checked.get('actual_source_page_count')
                    artifacts = connection.execute(text("SELECT id,page_index,width,height,reference FROM artifacts WHERE task_id=:task AND run_id=:run AND kind='corrected'"),
                                                   dict(task=task_id, run=row['run_id'])).mappings().all()
                    indices = [a['page_index'] for a in artifacts]
                    if type(count) is not int or count < 1 or sorted(indices) != list(range(1, count + 1)):
                        invalid('缺少原文件全部页面证据，请重跑或重新上传')
                    known_pages = {page['page_index']: page for page in pages}
                    for artifact in artifacts:
                        known_pages.setdefault(artifact['page_index'], dict(page_id=artifact['id'], page_index=artifact['page_index'],
                            width=artifact['width'], height=artifact['height'], extraction_method='pending', regions=[]))
                    pages = [known_pages[index] for index in sorted(known_pages)]
                    original['pages'] = pages
                    # A database reference alone does not prove readable page evidence.
                    from io import BytesIO
                    from PIL import Image
                    for artifact in artifacts:
                        try:
                            with Image.open(BytesIO(self.storage.read(artifact['reference']))) as image:
                                image.verify()
                        except Exception as error:
                            raise TaskError('INVALID_REQUEST', '页面证据无法读取，请重新处理', 422) from error
                    if coverage is not None:
                        if not isinstance(coverage, dict) or set(coverage) - {'pages', 'reason', 'regions'}:
                            invalid()
                        if (not isinstance(coverage.get('pages'), list) or any(type(i) is not int for i in coverage['pages'])
                                or sorted(coverage['pages']) != list(range(1, count + 1))):
                            invalid('须逐页核对原文件所有页面')
                        reason(coverage.get('reason'))
                        pending = {r['region_id'] for page in pages for r in page.get('regions', []) if r.get('status') != 'recognized'}
                        corrections = coverage.get('regions', [])
                        if not isinstance(corrections, list) or any(not isinstance(r, dict) for r in corrections):
                            invalid()
                        ids = [r.get('region_id') for r in corrections]
                        if len(ids) != len(set(ids)) or set(ids) != pending:
                            invalid('须对每个未完成区域明确补录或说明无业务内容')
                        for correction in corrections:
                            links = {'field_keys', 'item_ids', 'added_item_indexes', 'finding_ids', 'member_indexes', 'added_member_indexes', 'generic'}
                            if set(correction) - {'region_id', 'action', 'reason'} - links or correction.get('action') not in {'TRANSCRIBED', 'NO_CONTENT'}:
                                invalid()
                            reason(correction.get('reason'))
                            if correction['action'] == 'TRANSCRIBED':
                                supplied = {
                                    'field_keys': set(body.get('fields', {})),
                                    'item_ids': {i.get('item_id') for i in body.get('items', []) if isinstance(i, dict)},
                                    'added_item_indexes': set(range(len(body.get('added_items', [])))),
                                    'finding_ids': {i.get('finding_id') for i in body.get('findings', []) if isinstance(i, dict)},
                                    'member_indexes': {i.get('index') for i in body.get('members', []) if isinstance(i, dict)},
                                    'added_member_indexes': set(range(len(body.get('added_members', []))))}
                                linked = False
                                for key, available in supplied.items():
                                    value = correction.get(key, [])
                                    if not isinstance(value, list) or any(not isinstance(i, (str, int)) or isinstance(i, bool) for i in value) or not set(value) <= available:
                                        invalid('区域补录引用不属于本次提交')
                                    linked = linked or bool(value)
                                if correction.get('generic') is not None:
                                    if correction['generic'] is not True or not body.get('generic'):
                                        invalid()
                                    linked = True
                                if not linked:
                                    invalid('补录区域必须关联本次实际补正内容')
                        verified = True
                if row['status'] == 'FAILED' and not verified:
                    invalid('失败任务须完整逐页补正后才能创建人工版本')
                result = apply_review(original, body, actor=actor, coverage_verified=verified,
                                      required_overrides=self.required_policy(connection)['overrides'])
                result.setdefault('recognition_status', row['status'])
                result.setdefault('recognition_error', json.loads(row['error_json']) if row['error_json'] else None)
                result.update(task_id=task_id, run_id=row['run_id'], result_revision=row['revision'] + 1,
                              reviewed_by=actor, reviewed_at=now(), completion_origin='human_review')
                if result.get('error'):
                    result.pop('error')
                history = dict(task_id=task_id, run_id=row['run_id'], base_revision=row['revision'],
                               result_revision=row['revision'] + 1, actor=actor, at=now(), request=body,
                               before=original, after=result)
                reference = self.storage.put(json.dumps(history, ensure_ascii=False, allow_nan=False).encode())
                connection.execute(text("INSERT INTO artifacts(id,task_id,run_id,kind,reference) VALUES (:id,:task,:run,'review_revision',:ref)"),
                                   dict(id=identity(), task=task_id, run=row['run_id'], ref=reference))
                connection.execute(text('UPDATE tasks SET result_enc=:result,pages_enc=:pages,status=:status,revision=revision+1,error_json=NULL,updated_at=:at WHERE id=:id'),
                                   dict(result=self.storage.pack(result), pages=self.storage.pack(pages), status=result['status'], at=now(), id=task_id))
                self._audit(connection, 'human_review', actor, row, result_revision=row['revision'] + 1,
                            status=result['status'])
            return self.task(task_id)
        except BaseException:
            if reference is not None:
                self.storage.delete(reference)
            raise

    def cancel(self, task_id, run_id, revision, actor, *, user=None, authorize=None):
        with self.transaction() as connection:
            if authorize:
                authorize(connection)
            row = self._row(connection, task_id, user)
            self._expected(row, run_id, revision)
            if row['status'] not in ACTIVE | {'QUEUED'}:
                raise TaskError('INVALID_STATE', '当前任务状态不能取消')
            status = 'CANCELLED' if row['status'] == 'QUEUED' else row['status']
            connection.execute(text('UPDATE tasks SET cancel_requested=1,revision=revision+1,status=:status,updated_at=:at WHERE id=:id'),
                               dict(status=status, at=now(), id=task_id))
            if status == 'CANCELLED':
                connection.execute(text("UPDATE runs SET status='CANCELLED',ended_at=:at WHERE id=:id"), dict(at=now(), id=run_id))
            self._audit(connection, 'cancel_requested', actor, row)
        return self.task(task_id)

    def rerun(self, task_id, run_id, revision, actor, *, user=None, authorize=None):
        with self.transaction() as connection:
            if authorize:
                authorize(connection)
            row = self._row(connection, task_id, user)
            self._expected(row, run_id, revision)
            if row['status'] not in TERMINAL | {'NEED_REVIEW'}:
                raise TaskError('INVALID_STATE', '当前任务仍在运行')
            new_run = identity()
            connection.execute(text("INSERT INTO runs(id,task_id,status) VALUES (:run,:id,'QUEUED')"), dict(run=new_run, id=task_id))
            connection.execute(text("""UPDATE tasks SET run_id=:run,revision=revision+1,status='QUEUED',cancel_requested=0,
                progress=0,pages_enc=NULL,result_enc=NULL,error_json=NULL,active_started_at=NULL,stop_code=NULL,warnings_enc=:warnings,
                updated_at=:at WHERE id=:id"""),
                               dict(run=new_run, at=now(), id=task_id,
                                    warnings=self.storage.pack([w for w in self.storage.unpack(row['warnings_enc'], [])
                                                                if w.get('code') == 'DUPLICATE_FILE'])))
            self._audit(connection, 'task_rerun', actor, row, new_run_id=new_run)
        return self.task(task_id)

    def _recover_row(self, connection, row, code, message):
        status = 'CANCELLED' if row['cancel_requested'] else 'FAILED'
        error = None
        if status != 'CANCELLED':
            error = dict(code=code, message=message)
            if self.logger:
                error['error_id'] = self.logger.exception('task_interrupted', RuntimeError(code),
                    task_id=row['id'], run_id=row['run_id'], error_code=code)
        error_json = json.dumps(error, ensure_ascii=False) if error else None
        timestamp = now()
        connection.execute(text('UPDATE tasks SET status=:status,error_json=:error,revision=revision+1,updated_at=:at WHERE id=:id'),
                           dict(status=status, error=error_json, at=timestamp, id=row['id']))
        connection.execute(text('UPDATE runs SET status=:status,error_json=:error,ended_at=:at WHERE id=:id'),
                           dict(status=status, error=error_json, at=timestamp, id=row['run_id']))
        self._audit(connection, 'task_interrupted', task=row)

    def request_stop(self, task, code='EXTRACT_TIMEOUT', deadline=None):
        """Fence a precise active run; process termination must happen after commit."""
        if code == 'EXTRACT_TIMEOUT' and deadline is None:
            raise ValueError('Timeout fencing requires a monotonic deadline')
        with self.transaction() as connection:
            row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task['id']}).mappings().first()
            if (row is None or row['run_id'] != task['run_id'] or row['status'] not in ACTIVE
                    or row['active_started_at'] != task['active_started_at'] or row['stop_code']
                    or (deadline is not None and monotonic() < deadline)):
                return False
            connection.execute(text('UPDATE tasks SET stop_code=:code,updated_at=:at WHERE id=:id'),
                               dict(code=code, at=now(), id=task['id']))
            self._audit(connection, 'task_stop_requested', task=row, code=code)
        return True

    def finish_stopped(self, task, code='WORKER_INTERRUPTED', message='处理进程已停止，请检查诊断记录后重跑'):
        """Caller has confirmed the matching CPU child and model requests stopped."""
        with self.transaction() as connection:
            row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task['id']}).mappings().first()
            if (row is None or row['run_id'] != task['run_id'] or row['status'] not in ACTIVE
                    or row['active_started_at'] != task['active_started_at']):
                return False
            code = row['stop_code'] or code
            if code == 'EXTRACT_TIMEOUT':
                message = '任务超过180秒处理预算，请检查诊断记录后重跑'
            self._recover_row(connection, row, code, message)
        return True

    def timeout_run(self, task, deadline, stop):
        """Fence, confirm targeted stop outside SQLite, then recover the same run."""
        if not self.request_stop(task, deadline=deadline):
            return False
        from .runtime import RuntimeFailure
        try:
            confirmed = stop()
        except RuntimeFailure:
            raise
        except Exception as error:
            raise RuntimeFailure('SUPERVISION_FAILED') from error
        if confirmed is not True:
            raise RuntimeFailure('SUPERVISION_FAILED')
        if self.finish_stopped(task, code='EXTRACT_TIMEOUT'):
            return True
        # The coordinator can finish the fenced run while acknowledging stop.
        # This is success only for that exact execution, never a newer rerun.
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task['id']}).mappings().first()
            return bool(row and row['run_id'] == task['run_id'] and row['status'] in TERMINAL
                        and row['active_started_at'] == task['active_started_at'] and row['stop_code'])

    def recover(self, code='WORKER_INTERRUPTED', message='上次处理被中断，可显式重跑', only_task=None):
        """Caller must first prove the previous runtime tree has stopped."""
        with self.transaction() as connection:
            rows = connection.execute(text('SELECT * FROM tasks WHERE (:id IS NULL OR id=:id)'), {'id': only_task}).mappings().all()
            for row in rows:
                if row['status'] not in ACTIVE and not (row['status'] == 'QUEUED' and row['cancel_requested']):
                    continue
                self._recover_row(connection, row, code, message)

    def active(self):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text("SELECT * FROM tasks WHERE status IN ('PREPROCESSING','OCR','EXTRACTING','VALIDATING')")).mappings()]

    def delete_batch(self, batch_id, versions, actor, *, authorize):
        references = []
        with self.transaction() as connection:
            authorize(connection)
            if connection.execute(text('SELECT 1 FROM batches WHERE id=:id'), {'id': batch_id}).first() is None:
                raise TaskError('NOT_FOUND', '批次不存在或已经删除', 404)
            rows = connection.execute(text('SELECT * FROM tasks WHERE batch_id=:id'), {'id': batch_id}).mappings().all()
            expected = {v['task_id']: v for v in versions}
            if len(expected) != len(versions):
                raise TaskError('INVALID_REQUEST', '任务版本不能重复', 422)
            if set(expected) != {row['id'] for row in rows}:
                raise TaskError('RESULT_VERSION_CONFLICT', '批次任务已变化，请刷新后重新确认')
            if any(row['status'] not in TERMINAL | {'NEED_REVIEW'} for row in rows):
                raise TaskError('INVALID_STATE', '批次仍有排队或识别中的任务，请等待停止后再删除')
            for row in rows:
                version = expected[row['id']]
                self._expected(row, version['run_id'], version['expected_revision'])
            for row in rows:
                references.extend(connection.execute(text('SELECT reference FROM artifacts WHERE task_id=:id'), {'id': row['id']}).scalars())
                self._audit(connection, 'task_deleted', actor, row, batch_id=batch_id, result_revision=row['revision'])
            connection.execute(text('DELETE FROM tasks WHERE batch_id=:id'), {'id': batch_id})
            connection.execute(text('DELETE FROM batches WHERE id=:id'), {'id': batch_id})
            self._audit(connection, 'batch_deleted', actor, batch_id=batch_id, task_count=len(rows))
        cleanup_pending = False
        for reference in set(references):
            try:
                self.storage.delete(reference)
            except OSError as error:
                cleanup_pending = True
                if self.logger:
                    self.logger.exception('batch_cleanup_failed', error, batch_id=batch_id)
        return dict(batch_id=batch_id, task_ids=[row['id'] for row in rows], cleanup_pending=cleanup_pending)

    def cleanup(self, at=None):
        references = []
        with self.transaction() as connection:
            rows = connection.execute(text('SELECT * FROM tasks WHERE expires_at<=:at'), {'at': at or now()}).mappings().all()
            for row in rows:
                if row['status'] in ACTIVE:
                    continue
                references.extend(connection.execute(text('SELECT reference FROM artifacts WHERE task_id=:id'), {'id': row['id']}).scalars())
                self._audit(connection, 'task_expired', task=row)
                connection.execute(text('DELETE FROM tasks WHERE id=:id'), {'id': row['id']})
            connection.execute(text('DELETE FROM batches WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE batch_id=batches.id)'))
        for reference in references:
            self.storage.delete(reference)

    def cleanup_orphans(self):
        with self.engine.connect() as connection:
            references = set(connection.execute(text('SELECT reference FROM artifacts')).scalars())
        self.storage.cleanup_unreferenced(references)
