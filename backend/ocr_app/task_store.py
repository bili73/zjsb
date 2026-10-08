"""Durable task transitions. The worker never holds a transaction during OCR."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid
from time import monotonic

from sqlalchemy import bindparam, text

from .extraction import confirmed_abnormal

ACTIVE = {'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'}
TERMINAL = {'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'}
SUPPORTED = {'MEDICAL_REPORT', 'DIPLOMA', 'DEGREE_CERT'}


def now():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return str(uuid.uuid4())


class TaskError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


def mask_text(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r'(?<!\d)\d{17}[\dXx](?!\d)', lambda m: m[0][:3] + '*' * 11 + m[0][-4:], value)
    value = re.sub(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)',
                   lambda m: '****' + re.sub(r'\D', '', m[0])[-4:], value)
    return value


def masked(value):
    if isinstance(value, dict):
        # Business values are masked; validated structural identities must stay
        # round-trippable even when a UUID happens to contain mostly digits.
        return {k: v if isinstance(v, str) and (
            k.endswith('_id') and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', v)
            or k == 'error_id' and re.fullmatch(r'e_[0-9a-f]{32}', v)
            or k == 'content_hash' and re.fullmatch(r'[0-9a-f]{64}', v)
        ) else masked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [masked(v) for v in value]
    return mask_text(value)


class TaskStore:
    def __init__(self, engine, storage, logger=None):
        self.engine, self.storage, self.logger = engine, storage, logger

    @contextmanager
    def transaction(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            yield connection

    def _row(self, connection, task_id):
        row = connection.execute(text('SELECT * FROM tasks WHERE id=:id'), {'id': task_id}).mappings().first()
        if row is None:
            raise TaskError('INVALID_REQUEST', '任务不存在或已经到期清理', 404)
        return dict(row)

    def _audit(self, connection, event, actor='worker', task=None, **details):
        connection.execute(text('INSERT INTO audit VALUES (:id,:actor,:task,:run,:event,:at,:detail)'),
                           dict(id=identity(), actor=actor, task=task['id'] if task else None,
                                run=task['run_id'] if task else None, event=event, at=now(),
                                detail=json.dumps(details)))

    def create_batch(self, files, doc_type, actor, options=None):
        if doc_type not in SUPPORTED:
            raise TaskError('UNSUPPORTED_DOC_TYPE', '本阶段仅接收体检报告、毕业证和学位证，银行卡暂不接收', 422)
        batch, created, references, task_ids = identity(), now(), [], []
        try:
            with self.transaction() as connection:
                connection.execute(text('INSERT INTO batches VALUES (:id,:at,:name)'),
                                   dict(id=batch, at=created, name=self.storage.pack('上传批次')))
                hashes = {}
                for file in files:
                    digest = hashlib.sha256(file['data']).hexdigest()
                    if digest in hashes:
                        duplicate = self._row(connection, hashes[digest])
                        warnings = self.storage.unpack(duplicate['warnings_enc'], [])
                        warnings.append(dict(code='DUPLICATE_FILE', message='同批次重复文件已复用任务'))
                        connection.execute(text('UPDATE tasks SET warnings_enc=:value WHERE id=:id'),
                                           dict(value=self.storage.pack(warnings), id=duplicate['id']))
                        continue
                    task_id, run_id = identity(), identity()
                    reference = self.storage.put(file['data'])
                    references.append(reference)
                    duplicate = connection.execute(text('SELECT id FROM tasks WHERE content_hash=:hash LIMIT 1'),
                                                   {'hash': digest}).first()
                    warnings = [dict(code='DUPLICATE_FILE', message='其他批次存在相同文件，本批次独立处理')] if duplicate else []
                    params = dict(id=task_id, batch=batch, run=run_id, at=created,
                                  expires=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                                  hash=digest, doc=doc_type, reference=reference,
                                  meta=self.storage.pack(dict(file_name=file['name'], file_size=len(file['data']), mime_type=file['mime'])),
                                  options=self.storage.pack(options or {}), warnings=self.storage.pack(warnings))
                    connection.execute(text('''INSERT INTO tasks
                        (id,batch_id,run_id,status,created_at,updated_at,expires_at,content_hash,doc_type,input_ref,meta_enc,options_enc,warnings_enc)
                        VALUES (:id,:batch,:run,'QUEUED',:at,:at,:expires,:hash,:doc,:reference,:meta,:options,:warnings)'''), params)
                    connection.execute(text("INSERT INTO runs(id,task_id,status) VALUES (:run,:id,'QUEUED')"), params)
                    connection.execute(text("INSERT INTO artifacts(id,task_id,run_id,kind,reference) VALUES (:aid,:id,:run,'input',:reference)"),
                                       dict(params, aid=identity()))
                    self._audit(connection, 'task_created', actor, dict(id=task_id, run_id=run_id))
                    task_ids.append(task_id)
                    hashes[digest] = task_id
            return dict(batch_id=batch, task_ids=task_ids)
        except BaseException:
            for reference in references:
                self.storage.delete(reference)
            raise

    def _public(self, row):
        pages = self.storage.unpack(row['pages_enc'], [])
        return masked(dict(task_id=row['id'], batch_id=row['batch_id'], run_id=row['run_id'],
                           result_revision=row['revision'], cancel_requested=bool(row['cancel_requested']),
                           status=row['status'], progress=row['progress'], doc_type=row['doc_type'],
                           doc_type_confidence=None, doc_type_confidence_method='unavailable',
                           page_count=len(pages), pages=pages, content_hash=row['content_hash'],
                           created_at=row['created_at'], updated_at=row['updated_at'],
                           error=json.loads(row['error_json']) if row['error_json'] else None,
                           warnings=self.storage.unpack(row['warnings_enc'], []), summary=None,
                           need_review_fields=[], extract_options=self.storage.unpack(row['options_enc'], {}),
                           **self.storage.unpack(row['meta_enc'])))

    def task(self, task_id):
        with self.engine.connect() as connection:
            return self._public(self._row(connection, task_id))

    def tasks(self, batch_id=None, status=None):
        with self.engine.connect() as connection:
            rows = connection.execute(text('SELECT * FROM tasks WHERE (:batch IS NULL OR batch_id=:batch) '
                                           'AND (:status IS NULL OR status=:status) ORDER BY created_at,id'),
                                      dict(batch=batch_id, status=status)).mappings()
            return [self._public(row) for row in rows]

    def batch(self, batch_id):
        tasks = self.tasks(batch_id)
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT * FROM batches WHERE id=:id'), {'id': batch_id}).mappings().first()
            if row is None:
                raise TaskError('INVALID_REQUEST', '批次不存在或已到期清理', 404)
            counts = {state: sum(t['status'] == state for t in tasks) for state in TERMINAL | ACTIVE | {'QUEUED', 'NEED_REVIEW'}}
            if any(t['status'] not in TERMINAL for t in tasks) or not tasks:
                state = 'PROCESSING'
            elif counts['COMPLETED'] == len(tasks):
                state = 'COMPLETED'
            elif counts['CANCELLED'] == len(tasks):
                state = 'CANCELLED'
            else:
                state = 'PARTIAL' if counts['COMPLETED'] else 'FAILED'
            return dict(batch_id=batch_id, name=self.storage.unpack(row['name_enc']), display_name=self.storage.unpack(row['name_enc']),
                        status=state, task_count=len(tasks), file_count=len(tasks), total_count=len(tasks), completed_count=counts['COMPLETED'],
                        failed_count=counts['FAILED'], cancelled_count=counts['CANCELLED'], rejected_count=counts['REJECTED'],
                        need_review_count=counts['NEED_REVIEW'], created_at=row['created_at'],
                        updated_at=max((t['updated_at'] for t in tasks), default=row['created_at']), warnings=[])

    def batches(self, page=1, page_size=20):
        with self.engine.connect() as connection:
            ids = connection.execute(text('SELECT id FROM batches ORDER BY created_at DESC,id')).scalars().all()
        return dict(items=[self.batch(i) for i in ids[(page-1)*page_size:page*page_size]],
                    total=len(ids), page=page, page_size=page_size)

    def result(self, task_id, items_filter=None, include_normal_summary=True):
        with self.engine.connect() as connection:
            row = self._row(connection, task_id)
            result = self.storage.unpack(row['result_enc'])
            if result is None:
                raise TaskError('INVALID_STATE', '当前任务尚无可用识别结果')
            result.update(task_id=task_id, run_id=row['run_id'], result_revision=row['revision'], status=row['status'])
            options = self.storage.unpack(row['options_enc'], {})
            if result.get('doc_type') == 'MEDICAL_REPORT':
                selected = items_filter or ('flagged' if options.get('abnormal_only') else 'all')
                def abnormal(item):
                    return confirmed_abnormal(item)
                def unknown(item):
                    return item.get('abnormal_flag') == 'UNKNOWN' or (item.get('abnormal_flag') == 'POSITIVE' and not abnormal(item))
                if selected == 'flagged':
                    result['items'] = [i for i in result.get('items', []) if abnormal(i) or unknown(i)]
                elif selected == 'abnormal':
                    result['items'] = [i for i in result.get('items', []) if abnormal(i)]
                elif selected == 'unknown':
                    result['items'] = [i for i in result.get('items', []) if unknown(i)]
                if not include_normal_summary:
                    result['normal_summary'] = None
            return masked(result)

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
            connection.execute(text('''UPDATE tasks SET status=:status,progress=100,result_enc=:result,pages_enc=:pages,
                error_json=:error,warnings_enc=:warnings,revision=revision+1,updated_at=:at WHERE id=:id'''),
                               dict(status=status, result=current_payload, pages=current_pages,
                                    error=error_json, warnings=self.storage.pack(self.storage.unpack(row['warnings_enc'], []) + result.get('warnings', [])),
                                    at=now(), id=task['id']))
            self._audit(connection, 'task_' + status.lower(), task=row)
            return True

    def _expected(self, row, run_id, revision):
        if row['run_id'] != run_id or row['revision'] != revision:
            raise TaskError('RESULT_VERSION_CONFLICT', '任务版本已变化，请刷新后再操作')

    def cancel(self, task_id, run_id, revision, actor):
        with self.transaction() as connection:
            row = self._row(connection, task_id)
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

    def rerun(self, task_id, run_id, revision, actor):
        with self.transaction() as connection:
            row = self._row(connection, task_id)
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
