"""Owned model processes: one caller per model, independent ready-model execution."""
import copy
import json
import math
import os
import queue
import threading
import time

from .config import MODELS, ROOT
from .diagnostics import correlation_context, safe_context, session_diagnostics


class RuntimeFailure(Exception):
    def __init__(self, code, error_id=None):
        super().__init__(code)
        self.code = code
        self.error_id = error_id


class ModelProcess:
    def __init__(self, key, config, phase):
        from .winjob import JobProcess
        self.key, self.phase = key, phase
        self.responses = queue.Queue()
        self.serial = 0
        self.phase_state = 'loading'
        config.session_dir.mkdir(parents=True, exist_ok=True)
        self.diag = session_diagnostics(config.session_dir, 'model')
        environment = {**os.environ, 'OCR_DIAGNOSTICS_ROOT': str(self.diag.root),
                       'OCR_DIAGNOSTICS_SESSION': self.diag.session_id}
        try:
            self.process = JobProcess(config.model_command(key), cwd=ROOT, env=environment)
            self.diag.event('spawn_completed', model=key, child_pid=self.process.pid)
        except Exception as error:
            self.diag.exception('spawn_failed', error, model=key)
            self.diag.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.logger = threading.Thread(target=self._log, daemon=True)
        try:
            self.reader.start()
            self.logger.start()
        except Exception as error:
            self.diag.exception('reader_failed', error, model=key)
            self.process.close()
            for thread in (self.reader, self.logger):
                if thread.ident is not None:
                    thread.join(timeout=2)
            self.diag.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError as error:
                    self.diag.exception('protocol_failed', error, model=self.key)
                    self.responses.put({'protocol_error': True})
        except (OSError, ValueError) as error:
            self.diag.exception('reader_failed', error, model=self.key)
        finally:
            self.responses.put(None)

    def _log(self):
        count = lines = 0
        try:
            while chunk := self.process.stderr.read(4096):
                count += len(chunk)
                lines += chunk.count('\n')
        except (OSError, ValueError) as error:
            self.diag.exception('reader_failed', error, model=self.key)
        finally:
            self.diag.event('stderr_drained', model=self.key, stderr_characters=count, stderr_lines=lines)

    def call(self, operation, timeout, **payload):
        self.serial += 1
        request_id = self.serial
        context = correlation_context(payload.get('context'))
        context.setdefault('request_id', request_id)
        self.diag.event('request_started', model=self.key, operation=operation, **context)
        end = time.monotonic() + timeout
        try:
            self.process.stdin.write(json.dumps({'id': request_id, 'op': operation, **payload}) + '\n')
            self.process.stdin.flush()
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                message = self.responses.get(timeout=remaining)
                if message is None:
                    raise RuntimeFailure('MODEL_PROCESS_EXITED')
                if not isinstance(message, dict):
                    raise RuntimeFailure('MODEL_LOAD_FAILED')
                if message.get('protocol_error'):
                    raise RuntimeFailure('MODEL_LOAD_FAILED')
                if message.get('event') == 'phase':
                    if message.get('state') not in {'loading', 'warming'}:
                        raise RuntimeFailure('MODEL_LOAD_FAILED')
                    self.phase_state = message['state']
                    self.phase(self.key, self.phase_state)
                    continue
                if message.get('id') != request_id:
                    raise RuntimeFailure('MODEL_LOAD_FAILED')
                if not isinstance(message.get('ok'), bool):
                    raise RuntimeFailure('MODEL_LOAD_FAILED')
                if not message['ok']:
                    raise RuntimeFailure(message.get('error_code', 'MODEL_LOAD_FAILED'), message.get('error_id'))
                if not isinstance(message.get('result'), dict):
                    raise RuntimeFailure('MODEL_LOAD_FAILED')
                self.diag.event('request_completed', model=self.key, operation=operation, **context)
                return message['result']
        except queue.Empty:
            code = 'MODEL_WARMUP_FAILED' if self.phase_state == 'warming' else 'MODEL_LOAD_FAILED'
            self.diag.event('request_timeout', model=self.key, operation=operation,
                            timeout_seconds=timeout, phase=self.phase_state, **context)
            raise RuntimeFailure(code if operation == 'load' else 'MODEL_REQUEST_TIMEOUT')
        except (BrokenPipeError, OSError, ValueError) as error:
            error_id = self.diag.exception('request_failed', error, model=self.key, operation=operation, **context)
            raise RuntimeFailure('MODEL_PROCESS_EXITED', error_id) from error

    def poll(self):
        return self.process.poll()

    def close(self):
        # JobProcess confirms the entire job is empty before returning.
        try:
            self.process.stdin.close()
            self.process.wait(timeout=1.0)
        except (OSError, ValueError, TimeoutError):
            pass
        try:
            self.process.close()
            self.responses.put(None)
            self.reader.join(timeout=2)
            self.logger.join(timeout=2)
            self.diag.event('close_completed', model=self.key, child_pid=self.process.pid,
                            exit_code=self.process.poll())
        except Exception as error:
            self.diag.exception('close_failed', error, model=self.key)
            raise
        finally:
            self.diag.close()


class ModelManager:
    def __init__(self, config, publish=lambda value: None, factory=ModelProcess):
        self.config, self.publish, self.factory = config, publish, factory
        self.diag = session_diagnostics(config.session_dir, 'runtime')
        self.clients = {}
        self.recovery_used = {key: False for key in MODELS}
        self.pending_recovery = set()
        self.metrics = []
        self.view = dict(configured_mode=config.mode, effective_mode=None, state='starting',
                         models={key: 'unloaded' for key in MODELS}, reason_code=None)
        self.closed = False
        self.fatal = False
        self.starting = True
        self._state = threading.RLock()
        self._serial_execution = threading.Lock()
        self._execution = {key: threading.Lock() for key in MODELS}
        self._closing = {key: threading.Lock() for key in MODELS}
        self._owners = {}
        self._stopped_runs = set()
        self._revisions = {}
        self._generations = {key: 0 for key in MODELS}
        self._parallel_session = False

    @property
    def parallel_inference(self):
        # Session capability is latched only after successful dual startup. Losing
        # one model must not re-enable serial switching that unloads its peer.
        with self._state:
            return self._parallel_session and not self.closed

    def snapshot(self):
        with self._state:
            return copy.deepcopy(self.view)

    def statistics(self):
        with self._state:
            return dict(runtime=copy.deepcopy(self.view), metrics=copy.deepcopy(self.metrics),
                        model_pids={key: client.process.pid for key, client in self.clients.items()
                                    if hasattr(client, 'process')})

    def _record_metric(self, value):
        with self._state:
            self.metrics.append(value)

    def _emit(self):
        self.publish(self.snapshot())

    def _phase(self, key, state):
        if state not in {'loading', 'warming'}:
            raise RuntimeFailure('MODEL_LOAD_FAILED')
        with self._state:
            if self.view['models'][key] == 'stopping':
                return
            self.view['models'][key] = state
            self.diag.event('phase_changed', model=key, phase=state)
            self._emit()

    def _settle(self):
        with self._state:
            self._settle_locked()

    def _settle_locked(self):
        ready = sum(value == 'ready' for value in self.view['models'].values())
        if not ready:
            self.view.update(effective_mode='ocr_unavailable', state='degraded')
        elif ready == 2:
            self.view.update(effective_mode='dual_resident', state='ready')
        else:
            self.view['effective_mode'] = self.config.mode
            self.view['state'] = 'degraded' if self.config.mode == 'dual_resident' or self.view['reason_code'] else 'ready'
        if self.starting:
            self.view['state'] = 'starting'
        self._emit()

    def _unload(self, key, expected_client=None):
        if not self._closing[key].acquire(timeout=10):
            with self._state:
                self.fatal = self.closed = True
            raise RuntimeFailure('SUPERVISION_FAILED')
        try:
            with self._state:
                client = self.clients.get(key)
                if expected_client is not None and client is not expected_client:
                    return
                if client is None:
                    return
                self.view['models'][key] = 'stopping'
                self._emit()
            try:
                client.close()
            except Exception as error:
                error_id = self.diag.exception('close_failed', error, model=key)
                with self._state:
                    self.fatal = self.closed = True
                    self.view.update(state='degraded', reason_code='SUPERVISION_FAILED')
                    self._emit()
                raise RuntimeFailure('SUPERVISION_FAILED', error_id) from error
            with self._state:
                if self.clients.get(key) is client:
                    del self.clients[key]
                self.view['models'][key] = 'unloaded'
        finally:
            self._closing[key].release()

    def _failure(self, key, code, expected_client=None):
        with self._state:
            if expected_client is not None and self.clients.get(key) is not expected_client:
                return
        self.diag.event('model_failed', model=key, error_code=code)
        self._unload(key, expected_client)
        with self._state:
            if code == 'RESOURCE_LIMIT' and self.config.mode == 'single_resident':
                self.view['effective_mode'] = 'single_resident'
                if not self.recovery_used[key]:
                    self.pending_recovery.add(key)
                else:
                    self.view['models'][key] = 'failed'
            else:
                self.view['models'][key] = 'failed'
                self.pending_recovery.discard(key)
            public_code = code if code in {'RESOURCE_LIMIT', 'MODEL_LOAD_FAILED', 'MODEL_WARMUP_FAILED',
                                           'MODEL_PROCESS_EXITED', 'SUPERVISION_FAILED'} else 'MODEL_PROCESS_EXITED'
            self.view['reason_code'] = public_code
            self._settle()

    def _load(self, key, timeout, context=None):
        context = correlation_context(context)
        with self._state:
            self._check_owner(self._owners.get(key))
        if self.view['models'][key] == 'failed':
            raise RuntimeFailure('MODEL_LOAD_FAILED')
        if key in self.pending_recovery:
            self.recovery_used[key] = True
            self.pending_recovery.remove(key)
        self._phase(key, 'loading')
        begin = time.monotonic()
        client = None
        try:
            try:
                with self._state:
                    self._check_owner(self._owners.get(key))
                # OS spawn is outside the shared state lock. A stopped owner is
                # rechecked after registration and its just-created Job reclaimed.
                client = self.factory(key, self.config, self._phase)
                with self._state:
                    self.clients[key] = client
                    self._generations[key] += 1
                    if key in self._owners:
                        self._owners[key]['client'] = client
                    self._check_owner(self._owners.get(key))
            except RuntimeFailure:
                raise
            except Exception as error:
                error_id = self.diag.exception('spawn_failed', error, model=key)
                raise RuntimeFailure('SUPERVISION_FAILED', error_id) from error
            result = client.call('load', timeout=max(.001, timeout - (time.monotonic() - begin)), context=context)
            self._record_metric(dict(model=key, operation='load', wall_seconds=time.monotonic() - begin, **result))
            self.diag.event('model_loaded', model=key, duration_seconds=time.monotonic() - begin,
                            **{**context, **{name: value for name, value in safe_context(result).items()
                                            if name.endswith(('_seconds', '_gib', '_tokens'))}})
            with self._state:
                self._check_owner(self._owners.get(key))
                if self.clients.get(key) is not client:
                    raise RuntimeFailure('MODEL_PROCESS_EXITED')
                self._revisions[key] = result.get('revision')
                self.view['models'][key] = 'ready'
                self._emit()
        except RuntimeFailure as error:
            self._record_metric(dict(model=key, operation='load', wall_seconds=time.monotonic() - begin, error_code=error.code))
            if error.code == 'CANCELLED' and client is not None:
                self._unload(key, client)
                with self._state:
                    self.view['models'][key] = 'failed'
                    self._settle()
            elif error.code != 'CANCELLED':
                self._failure(key, error.code, client)
            raise

    def start(self):
        self._emit()
        for key in list(MODELS)[:2 if self.config.mode == 'dual_resident' else 1]:
            try:
                self._load(key, self.config.load_timeout)
            except RuntimeFailure as error:
                if error.code == 'SUPERVISION_FAILED':
                    raise
                if error.code == 'RESOURCE_LIMIT' and self.config.mode == 'single_resident':
                    # A surviving model stays resident; deferred switch gets one recovery.
                    if not self.clients:
                        try:
                            self._load(key, self.config.load_timeout)
                        except RuntimeFailure as recovery_error:
                            if recovery_error.code == 'SUPERVISION_FAILED':
                                raise
                    break
        with self._state:
            self.starting = False
            self._parallel_session = self.config.mode == 'dual_resident' and all(
                self.view['models'][key] == 'ready' for key in MODELS)
            self._settle()

    def check_processes(self):
        # Internal serial benchmarks may intentionally close a peer while its
        # execution lock is free. A health poll must not report that as a crash.
        serial = not self._parallel_session
        if serial and not self._serial_execution.acquire(blocking=False):
            return
        try:
            self._check_processes_idle()
        finally:
            if serial:
                self._serial_execution.release()

    def _check_processes_idle(self):
        with self._state:
            if self.fatal:
                raise RuntimeFailure('SUPERVISION_FAILED')
            clients = list(self.clients.items())
        for key, client in clients:
            if not self._execution[key].acquire(blocking=False):
                continue
            try:
                if client.poll() is not None:
                    self._failure(key, 'MODEL_PROCESS_EXITED', client)
            finally:
                self._execution[key].release()

    def _check_owner(self, owner):
        # Caller holds _state; raw identities are never written to model logs.
        if self.closed:
            raise RuntimeFailure('SUPERVISION_FAILED' if self.fatal else 'MODEL_PROCESS_EXITED')
        if owner and (owner['task_id'], owner['run_id']) in self._stopped_runs:
            raise RuntimeFailure('CANCELLED')

    def _acquire_execution(self, lock, deadline, owner):
        while True:
            with self._state:
                self._check_owner(owner)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeFailure('EXTRACT_TIMEOUT')
            if lock.acquire(timeout=min(.05, remaining)):
                return

    def stop_run(self, task_id, run_id):
        deadline = time.monotonic() + 10.
        with self._state:
            self._stopped_runs.add((task_id, run_id))
            owners = [(key, owner, owner['client']) for key, owner in self._owners.items()
                      if (owner['task_id'], owner['run_id']) == (task_id, run_id)]
            # Fence reuse of this same process before releasing state. Otherwise
            # the old owner could finish and a new run start before close takes
            # the per-model close lock, despite an identical client generation.
            for key, _, _ in owners:
                self.view['models'][key] = 'stopping'
        for key, owner, client in owners:
            if client is not None:
                self._unload(key, client)
                with self._state:
                    if self.clients.get(key) is None:
                        self.view['models'][key] = 'failed'
                        self.pending_recovery.discard(key)
                        self.view['reason_code'] = 'MODEL_PROCESS_EXITED'
                        self._settle()
            if not owner['done'].wait(max(0., deadline - time.monotonic())):
                with self._state:
                    self.fatal = self.closed = True
                raise RuntimeFailure('SUPERVISION_FAILED')
            if client is None:
                with self._state:
                    # A stop can win before OS spawn. No process was reusable,
                    # but the session must not remain permanently "stopping".
                    if self.clients.get(key) is None:
                        self.view['models'][key] = 'failed'
                        self.pending_recovery.discard(key)
                        self._settle()

    def recognize(self, key, image=None, task='ocr', timeout=None, max_new_tokens=4096, *, image_base64=None, context=None,
                  generation_timeout_seconds=None, _submitted_at=None):
        if key not in MODELS or task not in {'ocr', 'table'}:
            raise ValueError('Invalid recognition request')
        if self.closed:
            raise RuntimeFailure('SUPERVISION_FAILED' if self.fatal else 'MODEL_PROCESS_EXITED')
        if (image is None) == (image_base64 is None):
            raise RuntimeFailure('INPUT_INVALID')
        raw_context = context or {}
        owner = dict(task_id=raw_context.get('task_id'), run_id=raw_context.get('run_id'),
                     client=None, done=threading.Event())
        context = correlation_context(raw_context)
        requested = self.config.request_timeout if timeout is None else float(timeout)
        if not math.isfinite(requested) or requested <= 0 or not 1 <= max_new_tokens <= 4096:
            raise ValueError('Invalid recognition budget')
        soft = generation_timeout_seconds
        if soft is not None and (type(soft) not in (int, float) or not math.isfinite(soft) or soft <= 0):
            raise ValueError('Invalid generation budget')
        budget = min(requested, self.config.request_timeout)
        entered = time.monotonic()
        deadline = entered + budget
        submitted = entered if _submitted_at is None else _submitted_at
        serial_acquired = key_acquired = False
        try:
            if not self._parallel_session:
                self._acquire_execution(self._serial_execution, deadline, owner)
                serial_acquired = True
            self._acquire_execution(self._execution[key], deadline, owner)
            key_acquired = True
            with self._state:
                self._check_owner(owner)
                owner['client'] = self.clients.get(key)
                self._owners[key] = owner
            queue_wait = max(0., time.monotonic() - submitted)
            return self._recognize_owned(key, image, task, max_new_tokens, image_base64, context,
                                         soft, deadline, owner, queue_wait)
        finally:
            with self._state:
                if self._owners.get(key) is owner:
                    del self._owners[key]
                owner['done'].set()
            if key_acquired:
                self._execution[key].release()
            if serial_acquired:
                self._serial_execution.release()

    def _recognize_owned(self, key, image, task, max_new_tokens, image_base64, context, soft, deadline, owner, queue_wait):
        with self._state:
            self._check_owner(owner)
            if self.view['models'][key] in {'stopping', 'failed'}:
                raise RuntimeFailure('MODEL_LOAD_FAILED')
        if key not in self.clients:
            if self.config.mode == 'dual_resident' or self.view['models'][key] == 'failed':
                raise RuntimeFailure('MODEL_LOAD_FAILED')
            # Dual after startup never gains an unplanned extra model. Missing means switch/recovery.
            for other in list(self.clients):
                self._unload(other)
            self._load(key, max(.001, min(self.config.load_timeout, deadline - time.monotonic())), context=context)
            self._settle()
        started = time.monotonic()
        client = None
        try:
            with self._state:
                self._check_owner(owner)
                client = self.clients.get(key)
                if client is None:
                    raise RuntimeFailure('MODEL_PROCESS_EXITED')
                owner['client'] = client
            if started >= deadline:
                raise RuntimeFailure('MODEL_REQUEST_TIMEOUT')
            source = {'image_base64': image_base64} if image_base64 is not None else {'image': str(image)}
            rpc_timeout = deadline - started
            if soft is not None:
                # Loading remains separately bounded. Leave room for decode/IPC after soft stop.
                soft = min(soft, max(.001, rpc_timeout - 10.))
                source['generation_timeout_seconds'] = soft
                rpc_timeout = min(rpc_timeout, soft + 10.)
            result = client.call('recognize', timeout=rpc_timeout, **source,
                                            task=task, max_new_tokens=max_new_tokens, context=context)
            with self._state:
                self._check_owner(owner)
                result = {**result, 'model_revision': self._revisions.get(key),
                          'model_generation': self._generations[key], 'queue_wait_seconds': queue_wait}
            self._record_metric(dict(model=key, operation='recognize', wall_seconds=time.monotonic() - started,
                                     **{k: v for k, v in result.items() if k != 'text'}))
            self.diag.event('request_completed', model=key, operation='recognize',
                            **{**context, **{name: value for name, value in safe_context(result).items()
                                            if name.endswith(('_seconds', '_gib', '_tokens')) or name == 'termination_reason'},
                               'duration_seconds': time.monotonic() - started})
            return result
        except RuntimeFailure as error:
            self.diag.event('request_failed', model=key, error_code=error.code, error_id=error.error_id, **context)
            self._record_metric(dict(model=key, operation='recognize', wall_seconds=time.monotonic() - started,
                                     queue_wait_seconds=queue_wait, error_code=error.code))
            if error.code not in {'INPUT_INVALID', 'CANCELLED'}:
                self._failure(key, error.code, client)
            # The future task pipeline owns the explicit, bounded region retry; no hidden extra OCR attempt.
            raise

    def close(self):
        with self._state:
            self.closed = True
            self.view['state'] = 'stopping'
            clients = list(self.clients.items())
            owners = list(self._owners.values())
            self._emit()
        errors = []
        for key, client in clients:
            try:
                self._unload(key, client)
            except RuntimeFailure as error:
                errors.append(error)
        self._emit()
        deadline = time.monotonic() + 2.
        for owner in owners:
            if not owner['done'].wait(max(0., deadline - time.monotonic())):
                errors.append(RuntimeFailure('SUPERVISION_FAILED'))
        if errors:
            raise errors[0]
