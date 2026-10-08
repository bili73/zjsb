"""API-side process client. This module must never import torch/transformers."""
import copy
import json
import os
import queue
import sys
import threading
import time

from .config import MODELS, ROOT
from .runtime import RuntimeFailure
from .diagnostics import correlation_context, session_diagnostics

CLOSE_WAIT_SECONDS = 10.0  # 3s graceful request + 5s native termination + bounded reader joins.


class RuntimeClient:
    def __init__(self, config):
        self.config = config
        self.diag = session_diagnostics(config.session_dir, 'client')
        self.process = None
        self.lock = threading.RLock()
        self.requests = {}
        self.serial = 0
        self.closing = False
        self._close_done = threading.Event()
        self._close_deadline = None
        self._closed_confirmed = False
        self._close_error_id = None
        self.failed = False
        self.threads = []
        self.view = dict(configured_mode=config.mode, effective_mode=None, state='starting',
                         models={key: 'unloaded' for key in MODELS}, reason_code=None)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.view)

    def is_alive(self):
        with self.lock:
            return bool(self.process and self.process.poll() is None and not self.closing and not self.failed)

    def start(self):
        from .winjob import JobProcess
        with self.lock:
            if self.process or self.closing:
                return
            self.config.session_dir.mkdir(parents=True, exist_ok=True)
            try:
                command = [sys.executable, '-u', '-X', 'utf8',
                    str(ROOT / 'backend/runtime_worker.py'), '--mode', self.config.mode,
                    '--session-dir', str(self.config.session_dir)]
                if self.config.data_root is not None:
                    command += ['--data-root', str(self.config.data_root)]
                self.process = JobProcess(command, cwd=ROOT,
                    env={**os.environ, 'OCR_DIAGNOSTICS_ROOT': str(self.diag.root),
                         'OCR_DIAGNOSTICS_SESSION': self.diag.session_id})
                self.diag.event('spawn_completed', child_pid=self.process.pid)
            except Exception as error:
                self.diag.exception('runtime_start_failed', error)
                self.failed = True
                self.view.update(effective_mode='ocr_unavailable', state='degraded', reason_code='SUPERVISION_FAILED')
                return
            self.threads = [threading.Thread(target=self._read, daemon=True),
                            threading.Thread(target=self._log, daemon=True)]
            try:
                for thread in self.threads:
                    thread.start()
            except Exception as error:
                self.diag.exception('reader_failed', error)
                self.failed = True
                self.process.close()
                self.view.update(effective_mode='ocr_unavailable', state='degraded', reason_code='SUPERVISION_FAILED')

    def _log(self):
        count = lines = 0
        try:
            while chunk := self.process.stderr.read(4096):
                count += len(chunk)
                lines += chunk.count('\n')
        except (OSError, ValueError) as error:
            self.diag.exception('reader_failed', error)
        finally:
            self.diag.event('stderr_drained', stderr_characters=count, stderr_lines=lines)

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('Invalid runtime protocol')
                with self.lock:
                    if message.get('event') == 'snapshot' and not self.closing:
                        self.view = message['runtime']
                    elif message.get('id') in self.requests:
                        self.requests[message['id']].put(message)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.diag.exception('protocol_failed', error)
        finally:
            with self.lock:
                unexpected = not self.closing
                if not self.closing:
                    self.failed = True
                    self.view.update(state='degraded', effective_mode='ocr_unavailable', reason_code='MODEL_PROCESS_EXITED')
                    self.view['models'] = {key: 'failed' for key in MODELS}
                for reply in self.requests.values():
                    reply.put({'ok': False, 'error_code': 'MODEL_PROCESS_EXITED'})
            if unexpected and self.process:
                # Protocol corruption/EOF cannot leave an unobserved scheduler owning GPU work.
                try:
                    self.close(graceful=False)
                except Exception as error:
                    self.diag.exception('runtime_close_failed', error)
                finally:
                    # Reclamation after a crash must still be shown as failure,
                    # rather than looking like a user-requested normal shutdown.
                    self.view.update(state='degraded', effective_mode='ocr_unavailable',
                                     reason_code='SUPERVISION_FAILED' if self._close_error_id else 'MODEL_PROCESS_EXITED')
                    self.view['models'] = {key: 'failed' for key in MODELS}

    def request(self, op, wait=185.0, **payload):
        reply = queue.Queue()
        with self.lock:
            if self.closing and op != 'shutdown':
                raise RuntimeFailure('MODEL_PROCESS_EXITED')
            if not self.process or self.process.poll() is not None or self.failed:
                raise RuntimeFailure('MODEL_PROCESS_EXITED')
            if op != 'shutdown' and self.view['state'] == 'starting':
                raise RuntimeFailure('RUNTIME_STARTING')
            # Request IDs route independent replies; control must not wait for
            # another request before it can stop one specific Task execution.
            self.serial += 1
            request_id = self.serial
            context = correlation_context(payload.get('context'))
            context.setdefault('request_id', request_id)
            payload['context'] = context
            self.diag.event('request_started', operation=op, **context)
            self.requests[request_id] = reply
            try:
                self.process.stdin.write(json.dumps({'id': request_id, 'op': op, **payload}) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                error_id = self.diag.exception('writer_failed', error, operation=op, **context)
                del self.requests[request_id]
                raise RuntimeFailure('MODEL_PROCESS_EXITED', error_id) from error
        try:
            message = reply.get(timeout=wait)
            if not message['ok']:
                self.diag.event('request_failed', error_code=message['error_code'], error_id=message.get('error_id'), **context)
                raise RuntimeFailure(message['error_code'], message.get('error_id'))
            self.diag.event('request_completed', operation=op, **context)
            return message.get('result', {})
        except queue.Empty:
            self.diag.event('request_timeout', operation=op, timeout_seconds=wait, **context)
            # A stuck scheduler is not allowed to leave models executing indefinitely.
            # close() already owns a shutdown request. Its finally block will
            # force the Job closed; recursively waiting for itself would waste
            # the shared confirmation deadline before reaching that cleanup.
            if not (op == 'shutdown' and self.closing):
                self.close(graceful=False)
            raise RuntimeFailure('MODEL_REQUEST_TIMEOUT')
        finally:
            with self.lock:
                self.requests.pop(request_id, None)

    def stop_task(self, task):
        result = self.request('stop_task', wait=20.0, task_id=task['id'], run_id=task['run_id'])
        return (isinstance(result, dict) and result.get('stopped') is True
                and result.get('task_id') == task['id'] and result.get('run_id') == task['run_id'])

    def close(self, graceful=True):
        # A caller must never interpret "another thread is closing" as proof of
        # termination. All callers share one bounded confirmation/failure outcome.
        if not self.lock.acquire(timeout=1.0):
            raise RuntimeFailure('SUPERVISION_FAILED')
        try:
            owner = not self.closing
            if owner:
                self.closing = True
                self._close_deadline = time.monotonic() + CLOSE_WAIT_SECONDS
                self.view['state'] = 'stopping'
            process, deadline = self.process, self._close_deadline
        finally:
            self.lock.release()
        if not owner:
            if not self._close_done.wait(max(0.0, deadline - time.monotonic())):
                error_id = self.diag.exception('runtime_close_failed', TimeoutError('Close confirmation timed out'))
                raise RuntimeFailure('SUPERVISION_FAILED', error_id)
            if not self._closed_confirmed:
                raise RuntimeFailure('SUPERVISION_FAILED', self._close_error_id)
            return
        try:
            if process:
                try:
                    if graceful and process.poll() is None:
                        try:
                            self.request('shutdown', wait=3.0)
                        except RuntimeFailure:
                            pass
                finally:
                    process.close()
                if process.poll() is None:
                    raise RuntimeError('Owned process termination was not confirmed')
            self._closed_confirmed = True
            self.view['state'] = 'stopping'
            self.view['models'] = {key: 'unloaded' for key in MODELS}
            self.diag.event('close_completed', child_pid=getattr(process, 'pid', None),
                            exit_code=process.poll() if process else None)
        except Exception as error:
            self.failed = True
            self._close_error_id = self.diag.exception('runtime_close_failed', error)
            self.view.update(state='degraded', effective_mode='ocr_unavailable', reason_code='SUPERVISION_FAILED')
            raise RuntimeFailure('SUPERVISION_FAILED', self._close_error_id) from error
        finally:
            # Publish the kernel confirmation before joining readers: a reader may
            # itself be waiting on this event after detecting a corrupt protocol.
            self._close_done.set()
        for thread in self.threads:
            if thread.ident is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def is_stopped(self):
        return self._close_done.is_set() and self._closed_confirmed
