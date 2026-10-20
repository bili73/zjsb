"""Private coordinator for isolated document workers and model FIFO queues."""
import argparse
import contextlib
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path

from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, RuntimeFailure
from ocr_app.diagnostics import session_diagnostics

OUT = sys.stdout
EMIT_LOCK = threading.Lock()


def process_task(store, manager, task, logger, *, deadline=None):
    # Parser libraries may print informational messages. Only emit() owns the
    # private JSON-lines channel; raw third-party output is drained on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        return _process_task(store, manager, task, logger, deadline=deadline)


def _process_task(store, manager, task, logger, *, deadline=None):
    from ocr_app.pipeline import process_document
    began = time.monotonic()
    current_stage = 'PREPROCESSING'
    context = dict(task_id=task['id'], run_id=task['run_id'])
    if task.get('batch_id'):
        context['batch_id'] = task['batch_id']
    logger.event('task_claimed', **context)
    model_revisions = {}
    def refresh_revisions():
        for metric in getattr(manager, 'metrics', []):
            if metric.get('operation') == 'load':
                key, revision = metric.get('model'), metric.get('revision')
                if isinstance(revision, str) and revision:
                    model_revisions[key] = revision
                elif key:
                    model_revisions.pop(key, None)
    refresh_revisions()
    def progress(stage, percent, pages=None):
        nonlocal current_stage
        current_stage = stage
        store.progress(task, stage, percent, pages)
        logger.event('task_stage', **context, stage=stage, elapsed_seconds=time.monotonic()-began)
    def recognize(model, image_base64, task='ocr', timeout=180, **extra):
        try:
            return manager.recognize(model, task=task, image_base64=image_base64, timeout=timeout,
                                     max_new_tokens=extra.get('max_new_tokens', 4096),
                                     generation_timeout_seconds=extra.get('generation_timeout_seconds'),
                                     context={**context, **extra.get('context', {}), 'stage': 'OCR'})
        finally:
            refresh_revisions()
    def record_attempt(value):
        load = next((m for m in reversed(getattr(manager, 'metrics', []))
                     if m.get('model') == value['model'] and m.get('operation') == 'load' and m.get('revision')), {})
        prediction = value.get('prediction') or {}
        store.attempt(task, {**value, 'model_revision': load.get('revision'),
                             'max_new_tokens': prediction.get('max_new_tokens', value.get('max_new_tokens', 4096)),
                             'generation_timeout_seconds': prediction.get('generation_timeout_seconds', value.get('generation_timeout_seconds')),
                             'prompt': 'Table Recognition:' if value['task'] == 'table' else (
                                 'Text Recognition:' if value['model'] == 'glm_ocr' else 'OCR:')})
    try:
        content = store.storage.read(task['input_ref'])
        result = process_document(content, task['doc_type'], recognize=recognize, progress=progress,
                                  save_page=lambda index, png, width, height: store.save_page(task, index, png, width, height),
                                  record_attempt=record_attempt,
                                  cancelled=lambda: store.cancelled(task['id'], task['run_id']),
                                  deadline=began+180 if deadline is None else deadline,
                                  options=store.storage.unpack(task['options_enc'], {}),
                                  model_revisions=model_revisions,
                                  required_overrides=store.required_policy()['overrides']
                                  if task['doc_type'] in {'DIPLOMA', 'DEGREE_CERT'} else None)
        if result.get('error'):
            if not result['error'].get('error_id'):
                result['error']['error_id'] = logger.exception('pipeline_failed', RuntimeError(result['error']['code']), **context,
                                                              stage=result['error'].get('stage'), error_code=result['error']['code'])
        result['elapsed_seconds'] = time.monotonic()-began
        store.publish(task, result)
        logger.event('task_cancelled' if result['status'] == 'CANCELLED' else
                     'pipeline_failed' if result['status'] == 'FAILED' else 'task_completed',
                     **context, elapsed_seconds=time.monotonic()-began)
    except Exception as error:
        error_id = logger.exception('pipeline_failed', error, **context, stage=current_stage)
        if getattr(error, 'code', None) == 'SUPERVISION_FAILED':
            # Publication/recovery is unsafe until the owner proves the old Job
            # has stopped. Exit this scheduler and let its owner recover tasks.
            raise
        pages = store.task(task['id']).get('pages', [])
        store.publish(task, dict(status='FAILED', doc_type=task['doc_type'], pages=pages, fields=[], review_issues=[],
                                 error=dict(code='INTERNAL_ERROR', message='文件处理失败，请保存错误编号查看诊断记录',
                                            error_id=error_id, stage=current_stage)))


def emit(value):
    with EMIT_LOCK:
        print(json.dumps(value, ensure_ascii=False), file=OUT, flush=True)


def submit_recognition(models, config, message):
    """Standalone private probes use the same queues, with an isolated RPC owner."""
    timeout = message.get('timeout')
    timeout = config.request_timeout if timeout is None else timeout
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Invalid timeout')
    payload = {key: message[key] for key in ('image', 'image_base64', 'task', 'max_new_tokens',
               'generation_timeout_seconds') if key in message}
    payload.setdefault('task', 'ocr')
    return models.submit(message['model'], payload, task_id='rpc-' + str(message['id']),
                         run_id='private-rpc', request_id=message['id'], context=message.get('context'),
                         deadline=time.monotonic() + timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True)
    ap.add_argument('--session-dir', type=Path, required=True)
    ap.add_argument('--data-root', type=Path)
    ap.add_argument('--model-batch-size', type=int, choices=(1, 2), default=1)
    args = ap.parse_args()
    config = RuntimeConfig(args.session_dir, args.mode, data_root=args.data_root,
                           model_batch_size=args.model_batch_size)
    manager = ModelManager(config, lambda value: emit({'event': 'snapshot', 'runtime': value}))
    logger = session_diagnostics(args.session_dir, 'runtime')
    store = None
    if args.data_root:
        from ocr_app.storage import Storage
        from ocr_app.db import open_database
        from ocr_app.task_store import TaskStore
        try:
            store = TaskStore(open_database(args.data_root, migrate=False), Storage(args.data_root), logger)
        except Exception as error:
            logger.exception('storage_failed', error, stage='BOOTSTRAP')
            raise
    incoming = queue.Queue()
    completed = queue.Queue()
    def receive():
        try:
            for line in sys.stdin:
                incoming.put(json.loads(line))
        finally:
            incoming.put(None)
    threading.Thread(target=receive, daemon=True).start()
    models = scheduler = None
    try:
        manager.start()
        from ocr_app.model_queues import ModelQueues
        from ocr_app.task_scheduler import TaskScheduler
        models = ModelQueues(manager)
        if store:
            scheduler = TaskScheduler(store, manager, models, config, logger, emit)
        while True:
            manager.check_processes()
            if scheduler:
                scheduler.poll()
            while not completed.empty():
                identity, future = completed.get_nowait()
                try:
                    emit(dict(id=identity, ok=True, result=future.result()))
                except RuntimeFailure as error:
                    emit(dict(id=identity, ok=False, error_code=error.code, error_id=error.error_id))
                    if error.code == 'SUPERVISION_FAILED':
                        raise
            try:
                message = incoming.get(timeout=.05)
            except queue.Empty:
                continue
            if message is None:
                break
            try:
                op = message['op']
                if op == 'recognize':
                    future = submit_recognition(models, config, message)
                    future.add_done_callback(lambda value, identity=message['id']: completed.put((identity, value)))
                    continue
                elif op == 'stop_task':
                    if not all(isinstance(message.get(key), str) and message[key] for key in ('task_id', 'run_id')):
                        raise ValueError('Invalid task identity')
                    if scheduler:
                        scheduler.stop_task(message['task_id'], message['run_id'], message['id'])
                        continue
                    result = dict(stopped=False, task_id=message['task_id'], run_id=message['run_id'])
                elif op == 'statistics':
                    result = manager.statistics()
                elif op == 'shutdown':
                    if scheduler:
                        scheduler.close()
                    models.close()
                    emit({'id': message['id'], 'ok': True, 'result': {}})
                    return
                else:
                    raise ValueError('Invalid internal operation')
                emit({'id': message['id'], 'ok': True, 'result': result})
            except RuntimeFailure as error:
                emit({'id': message['id'], 'ok': False, 'error_code': error.code, 'error_id': error.error_id})
                if error.code == 'SUPERVISION_FAILED':
                    return
            except (KeyError, ValueError, TypeError):
                emit({'id': message.get('id'), 'ok': False, 'error_code': 'INVALID_REQUEST'})
    finally:
        try:
            if scheduler:
                scheduler.close()
        finally:
            try:
                models.close() if models else manager.close()
            finally:
                if store:
                    store.engine.dispose()


if __name__ == '__main__':
    main()
