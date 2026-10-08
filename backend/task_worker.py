"""One supervised document process; recognition is owned by the coordinator."""
import argparse
import json
import sys
from pathlib import Path

from ocr_app.db import open_database
from ocr_app.diagnostics import session_diagnostics
from ocr_app.runtime import RuntimeFailure
from ocr_app.storage import Storage
from ocr_app.task_store import TaskStore
from runtime_worker import process_task

OUT = sys.stdout


def emit(value):
    print(json.dumps(value, ensure_ascii=False), file=OUT, flush=True)


class QueuedManager:
    def __init__(self, revisions):
        self.serial = 0
        self.metrics = [dict(model=model, operation='load', revision=revision)
                        for model, revision in revisions.items() if isinstance(revision, str)]

    def recognize(self, model, image=None, task='ocr', **payload):
        self.serial += 1
        identity = self.serial
        emit(dict(op='recognize', id=identity, model=model, image=image, task=task, **payload))
        line = sys.stdin.readline()
        if not line:
            raise RuntimeFailure('MODEL_PROCESS_EXITED')
        message = json.loads(line)
        if not isinstance(message, dict) or message.get('id') != identity:
            raise RuntimeFailure('SUPERVISION_FAILED')
        if not message.get('ok'):
            raise RuntimeFailure(message.get('error_code', 'MODEL_PROCESS_EXITED'), message.get('error_id'))
        result = message['result']
        revision = result.get('model_revision')
        if isinstance(revision, str):
            self.metrics.append(dict(model=model, operation='load', revision=revision))
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--session-dir', type=Path, required=True)
    args = parser.parse_args()
    initial = json.loads(sys.stdin.readline())
    logger = session_diagnostics(args.session_dir, 'runtime')
    store = TaskStore(open_database(args.data_root, migrate=False), Storage(args.data_root), logger)
    try:
        task = next((row for row in store.active()
                     if row['id'] == initial['task_id'] and row['run_id'] == initial['run_id']), None)
        if task is None:
            raise RuntimeFailure('MODEL_PROCESS_EXITED')
        manager = QueuedManager(initial.get('model_revisions', {}))
        process_task(store, manager, task, logger, deadline=initial['deadline'])
        emit(dict(event='done', task_id=task['id'], run_id=task['run_id']))
    except Exception as error:
        logger.exception('pipeline_failed', error)
        raise SystemExit(1) from None
    finally:
        store.engine.dispose()
        logger.close()


if __name__ == '__main__':
    main()
