"""Two bounded document processes sharing independently owned model queues."""
from dataclasses import dataclass, field
import json
import math
import os
import queue
import sys
import threading
import time

from .config import MODELS, ROOT
from .runtime import RuntimeFailure


class TaskProcess:
    def __init__(self, config, task, deadline, revisions, logger):
        from .winjob import JobProcess
        self.logger, self.task = logger, task
        self.messages = queue.Queue()
        self.write_lock = threading.Lock()
        command = [sys.executable, '-B', '-u', '-X', 'utf8', str(ROOT / 'backend/task_worker.py'),
                   '--data-root', str(config.data_root), '--session-dir', str(config.session_dir)]
        self.process = JobProcess(command, cwd=ROOT, env=dict(os.environ))
        self.threads = [threading.Thread(target=self._read, daemon=True),
                        threading.Thread(target=self._drain, daemon=True)]
        try:
            for thread in self.threads:
                thread.start()
            self.send(dict(task_id=task['id'], run_id=task['run_id'], deadline=deadline,
                           model_revisions=revisions))
        except BaseException:
            self.process.close()
            raise
        logger.event('spawn_completed', child_pid=self.process.pid,
                     task_id=task['id'], run_id=task['run_id'])

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('Invalid private task protocol')
                self.messages.put(message)
        except (OSError, ValueError, TypeError) as error:
            self.logger.exception('protocol_failed', error,
                                  task_id=self.task['id'], run_id=self.task['run_id'])
            self.messages.put({'event': 'protocol_failed'})
        finally:
            self.messages.put({'event': 'eof'})

    def _drain(self):
        count = lines = 0
        try:
            while chunk := self.process.stderr.read(4096):
                count += len(chunk)
                lines += chunk.count('\n')
        except (OSError, ValueError):
            pass
        self.logger.event('stderr_drained', task_id=self.task['id'], run_id=self.task['run_id'],
                          stderr_characters=count, stderr_lines=lines)

    def send(self, value):
        with self.write_lock:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.process.stdin.flush()

    def poll(self):
        return self.process.poll()

    def close(self):
        self.process.close()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=1)


@dataclass
class ActiveTask:
    task: dict
    lane: str
    child: object
    deadline: float
    pending: dict = field(default_factory=dict)
    stopping: bool = False
    stop_thread: threading.Thread | None = None
    control_ids: list = field(default_factory=list)


class TaskScheduler:
    def __init__(self, store, manager, models, config, logger, reply, factory=TaskProcess):
        self.store, self.manager, self.models = store, manager, models
        self.config, self.logger, self.reply, self.factory = config, logger, reply, factory
        self.parallel = bool(getattr(manager, 'parallel_inference', False))
        from .doc_profiles import catalogue
        paddle_types = {'MEDICAL_REPORT', 'TABLE', 'GENERIC', 'INTERVIEW_FORM'}
        document_types = {entry['doc_type'] for entry in catalogue()} - paddle_types
        self.lanes = {'certificate': document_types, 'medical': paddle_types} if self.parallel else {'all': None}
        self.jobs = {}
        self.closed_runs = set()
        self.events = queue.Queue()
        self.closing = False
        self.last_cleanup = time.monotonic()

    @staticmethod
    def identity(task):
        return task['id'], task['run_id']

    def revisions(self):
        revisions = {}
        for metric in list(self.manager.metrics):
            if metric.get('operation') == 'load' and metric.get('revision'):
                revisions[metric['model']] = metric['revision']
        return revisions

    def _current(self, job):
        return self.jobs.get(self.identity(job.task)) is job

    def _recognize(self, job, message):
        identity = message.get('id')
        if (job.pending or type(identity) is not int or identity <= 0 or
                message.get('op') != 'recognize' or message.get('model') not in MODELS or
                message.get('task') not in {'ocr', 'table'}):
            raise RuntimeFailure('SUPERVISION_FAILED')
        timeout = message.get('timeout', max(.001, job.deadline - time.monotonic()))
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise RuntimeFailure('SUPERVISION_FAILED')
        payload = {key: message[key] for key in ('image', 'image_base64', 'task', 'max_new_tokens',
                   'generation_timeout_seconds') if key in message}
        future = self.models.submit(message['model'], payload,
                                    task_id=job.task['id'], run_id=job.task['run_id'], request_id=identity,
                                    context=message.get('context'), deadline=min(job.deadline, time.monotonic() + timeout))
        job.pending[identity] = future
        future.add_done_callback(lambda result: self.events.put(('reply', job, identity, result)))

    def _begin_stop(self, job, control_id=None):
        if control_id is not None:
            job.control_ids.append(control_id)
        if job.stopping:
            return
        job.stopping = True

        def stop():
            error = None
            try:
                # This run is fenced in the DB before its processes can publish.
                self.store.request_stop(job.task, code='WORKER_INTERRUPTED')
                self.models.stop_run(*self.identity(job.task))
                job.child.close()
                self.store.finish_stopped(job.task)
            except BaseException as failure:
                error = failure
            self.events.put(('stopped', job, error))
        job.stop_thread = threading.Thread(target=stop, name='stop-document', daemon=True)
        job.stop_thread.start()

    def stop_task(self, task_id, run_id, control_id):
        identity = task_id, run_id
        job = self.jobs.get(identity)
        if job:
            self._begin_stop(job, control_id)
        else:
            self.reply(dict(id=control_id, ok=True, result=dict(stopped=identity in self.closed_runs,
                                                              task_id=task_id, run_id=run_id)))

    def _events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == 'reply':
                _, job, identity, future = event
                if not self._current(job) or job.stopping:
                    continue
                job.pending.pop(identity, None)
                try:
                    value = dict(id=identity, ok=True, result=future.result())
                except RuntimeFailure as error:
                    if error.code == 'SUPERVISION_FAILED':
                        raise
                    value = dict(id=identity, ok=False, error_code=error.code, error_id=error.error_id)
                except Exception as error:
                    error_id = self.logger.exception('request_failed', error,
                        task_id=job.task['id'], run_id=job.task['run_id'])
                    value = dict(id=identity, ok=False, error_code='INTERNAL_ERROR', error_id=error_id)
                try:
                    job.child.send(value)
                except (OSError, ValueError):
                    self._begin_stop(job)
            elif event[0] == 'stopped':
                _, job, error = event
                if error is not None:
                    error_id = self.logger.exception('close_failed', error,
                        task_id=job.task['id'], run_id=job.task['run_id'])
                    raise RuntimeFailure('SUPERVISION_FAILED', error_id) from error
                self.closed_runs.add(self.identity(job.task))
                if self._current(job):
                    del self.jobs[self.identity(job.task)]
                for identity in job.control_ids:
                    self.reply(dict(id=identity, ok=True, result=dict(stopped=True,
                                   task_id=job.task['id'], run_id=job.task['run_id'])))

    def poll(self):
        self._events()
        for job in list(self.jobs.values()):
            if job.stopping:
                continue
            if self.store.cancelled(*self.identity(job.task)):
                self._begin_stop(job)
                continue
            # Recognition/queue budget ends at 180s. Preserve the existing 1s
            # watchdog margin for the child to publish bounded partial evidence.
            if time.monotonic() >= job.deadline + 1:
                self.store.request_stop(job.task, code='EXTRACT_TIMEOUT', deadline=job.deadline + 1)
                self._begin_stop(job)
                continue
            while True:
                try:
                    message = job.child.messages.get_nowait()
                except queue.Empty:
                    break
                if message.get('op') == 'recognize':
                    self._recognize(job, message)
                elif message.get('event') in {'done', 'eof', 'protocol_failed'}:
                    self._begin_stop(job)
                    break
                else:
                    raise RuntimeFailure('SUPERVISION_FAILED')
            if not job.stopping and job.child.poll() is not None:
                self._begin_stop(job)
        if self.closing:
            return
        for lane, types in self.lanes.items():
            if any(job.lane == lane for job in self.jobs.values()):
                continue
            task = self.store.claim_next(types, lane=lane)
            if task is None:
                continue
            deadline = time.monotonic() + 180
            try:
                child = self.factory(self.config, task, deadline, self.revisions(), self.logger)
            except Exception as error:
                error_id = self.logger.exception('spawn_failed', error,
                    task_id=task['id'], run_id=task['run_id'])
                raise RuntimeFailure('SUPERVISION_FAILED', error_id) from error
            self.jobs[self.identity(task)] = ActiveTask(task, lane, child, deadline)
        if not self.jobs and time.monotonic() - self.last_cleanup > 60:
            self.store.cleanup()
            self.last_cleanup = time.monotonic()

    def close(self):
        self.closing = True
        for job in list(self.jobs.values()):
            self._begin_stop(job)
        deadline = time.monotonic() + 20
        for job in list(self.jobs.values()):
            job.stop_thread.join(timeout=max(0, deadline-time.monotonic()))
            if job.stop_thread.is_alive():
                raise RuntimeFailure('SUPERVISION_FAILED')
        self._events()
