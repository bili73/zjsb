"""Two bounded-owner FIFO consumers; queued expiry never stops another run."""
from collections import deque
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass, field
import math
import threading
import time

from .config import MODELS
from .batch_generation import compatible
from .runtime import RuntimeFailure


@dataclass
class _Request:
    model: str
    payload: dict
    context: dict
    deadline: float
    future: Future = field(default_factory=Future)
    done: threading.Event = field(default_factory=threading.Event)
    submitted_at: float = field(default_factory=time.monotonic)

    @property
    def run(self):
        return self.context['task_id'], self.context['run_id']


class ModelQueues:
    def __init__(self, manager):
        self.manager = manager
        self.batch_size = 2 if getattr(manager, 'model_batch_size', 1) == 2 else 1
        self._condition = threading.Condition()
        self._pending = {model: deque() for model in MODELS}
        self._active = {}
        self._stopped_runs = set()
        self._closed = False
        self._close_lock = threading.Lock()
        self.threads = [threading.Thread(target=self._consume, args=(model,),
                        name='ocr-model-' + model, daemon=True) for model in MODELS]
        self.threads.append(threading.Thread(target=self._expire, name='ocr-queue-expiry', daemon=True))
        try:
            for thread in self.threads:
                thread.start()
        except Exception:
            self.close()
            raise

    @staticmethod
    def _fail(request, code):
        # A caller may cancel a Future while it is still queued.
        if not request.future.done():
            try:
                request.future.set_exception(RuntimeFailure(code))
            except InvalidStateError:
                if not request.future.cancelled():
                    raise
        request.payload.clear()
        request.done.set()

    def submit(self, model, payload, *, task_id=None, run_id=None, request_id=None,
               context=None, deadline):
        if model not in MODELS or not isinstance(payload, dict):
            raise ValueError('Invalid recognition request')
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid queue deadline')
        correlation = {**payload.get('context', {}), **(context or {})}
        for name, value in (('task_id', task_id), ('run_id', run_id), ('request_id', request_id)):
            if value is not None:
                correlation[name] = value
        if any(not isinstance(correlation.get(key), str) or not correlation[key] for key in ('task_id', 'run_id')):
            raise ValueError('Task and run identity required')
        allowed = {'image', 'image_base64', 'task', 'max_new_tokens', 'generation_timeout_seconds'}
        if set(payload) - allowed - {'context'}:
            raise ValueError('Invalid recognition payload')
        request = _Request(model, {k: v for k, v in payload.items() if k in allowed}, correlation, deadline)
        error = None
        with self._condition:
            if self._closed:
                error = 'MODEL_PROCESS_EXITED'
            elif request.run in self._stopped_runs:
                error = 'CANCELLED'
            elif deadline <= time.monotonic():
                error = 'EXTRACT_TIMEOUT'
            else:
                self._pending[model].append(request)
                self._condition.notify_all()
        if error:
            self._fail(request, error)
        return request.future

    def _consume(self, model):
        if self.batch_size == 2:
            return self._consume_batches(model)
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending[model])
                if self._closed:
                    return
                request = self._pending[model].popleft()
                self._active[model] = request
            try:
                if not request.future.set_running_or_notify_cancel():
                    continue
                with self._condition:
                    stopped = self._closed or request.run in self._stopped_runs
                if stopped:
                    raise RuntimeFailure('CANCELLED')
                remaining = request.deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeFailure('EXTRACT_TIMEOUT')
                result = self.manager.recognize(model, timeout=remaining,
                                               context=request.context, _submitted_at=request.submitted_at,
                                               **request.payload)
                with self._condition:
                    stopped = self._closed or request.run in self._stopped_runs
                if stopped:
                    raise RuntimeFailure('CANCELLED')
                request.future.set_result(result)
            except Exception as error:
                # Never include arbitrary exception text containing image paths.
                failure = error if isinstance(error, RuntimeFailure) else RuntimeFailure(
                    'INPUT_INVALID' if isinstance(error, (ValueError, TypeError)) else 'MODEL_PROCESS_EXITED')
                if not request.future.done():
                    request.future.set_exception(failure)
            finally:
                request.payload.clear()
                with self._condition:
                    if self._active.get(model) is request:
                        del self._active[model]
                    request.done.set()
                    self._condition.notify_all()

    def _consume_batches(self, model):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending[model])
                if self._closed:
                    return
                pending = self._pending[model]
                selected = [pending.popleft()]
                # Recovery crops keep document context better in a single-image call.
                # Never skip a marked head to find a different batch partner.
                if (pending and selected[0].context.get('batch_policy') != 'single'
                        and pending[0].context.get('batch_policy') != 'single'
                        and compatible(selected[0].payload, pending[0].payload)):
                    selected.append(pending.popleft())
                self._active[model] = selected
            live = []
            try:
                for request in selected:
                    if not request.future.set_running_or_notify_cancel():
                        request.done.set()
                        continue
                    with self._condition:
                        stopped = self._closed or request.run in self._stopped_runs
                    if stopped or request.deadline <= time.monotonic():
                        self._fail(request, 'CANCELLED' if stopped else 'EXTRACT_TIMEOUT')
                    else:
                        live.append(request)
                def delivered(index, result, error):
                    request = live[index]
                    with self._condition:
                        stopped = self._closed or request.run in self._stopped_runs
                    if stopped:
                        error = RuntimeFailure('CANCELLED')
                    request.done.set()
                    request.payload.clear()
                    if error is not None:
                        if not request.future.done():
                            request.future.set_exception(error)
                    elif not request.future.done():
                        request.future.set_result(result)
                if live:
                    self.manager.recognize_batch(model, [dict(payload=dict(request.payload), context=request.context,
                        deadline=request.deadline, submitted_at=request.submitted_at) for request in live], delivered)
                    if any(not request.future.done() for request in live):
                        raise RuntimeFailure('MODEL_PROCESS_EXITED')
            except Exception as caught:
                error = caught if isinstance(caught, RuntimeFailure) else RuntimeFailure('MODEL_PROCESS_EXITED')
                for request in selected:
                    if not request.future.done():
                        request.future.set_exception(error)
            finally:
                for request in selected:
                    request.payload.clear()
                    request.done.set()
                with self._condition:
                    if self._active.get(model) is selected:
                        del self._active[model]
                    self._condition.notify_all()

    def _expire(self):
        # A busy consumer cannot drain its queue; this small monitor expires only
        # waiting requests and never operates on a model process.
        while True:
            expired = []
            with self._condition:
                if self._closed:
                    return
                now = time.monotonic()
                for model, pending in self._pending.items():
                    keep = deque()
                    for request in pending:
                        if request.future.cancelled() or request.deadline <= now:
                            expired.append(request)
                        else:
                            keep.append(request)
                    self._pending[model] = keep
            for request in expired:
                self._fail(request, 'EXTRACT_TIMEOUT')
            with self._condition:
                self._condition.wait(timeout=.05)

    def stop_run(self, task_id, run_id):
        identity = (task_id, run_id)
        removed = []
        with self._condition:
            self._stopped_runs.add(identity)
            for model, pending in self._pending.items():
                removed.extend(request for request in pending if request.run == identity)
                self._pending[model] = deque(request for request in pending if request.run != identity)
            active = [request for value in self._active.values()
                      for request in (value if isinstance(value, list) else [value]) if request.run == identity]
            self._condition.notify_all()
        for request in removed:
            self._fail(request, 'CANCELLED')
        # Manager independently fences the same run before consulting its current
        # owner. This covers the consumer-pop -> manager-dispatch race.
        self.manager.stop_run(task_id, run_id)
        deadline = time.monotonic() + 2.
        for request in active:
            # Future callbacks run on this consumer. A completed future already
            # has no model owner and must not wait for its own callback to return.
            if not request.future.done() and not request.done.wait(max(0., deadline - time.monotonic())):
                raise RuntimeFailure('SUPERVISION_FAILED')

    def close(self):
        if not self._close_lock.acquire(timeout=25):
            raise RuntimeFailure('SUPERVISION_FAILED')
        try:
            with self._condition:
                self._closed = True
                pending = [request for queue in self._pending.values() for request in queue]
                for queue in self._pending.values():
                    queue.clear()
                self._condition.notify_all()
            for request in pending:
                self._fail(request, 'MODEL_PROCESS_EXITED')
            error = None
            try:
                self.manager.close()
            except Exception as failure:
                error = failure
            deadline = time.monotonic() + 2.
            for thread in self.threads:
                if thread.ident is not None and thread is not threading.current_thread():
                    thread.join(timeout=max(0., deadline - time.monotonic()))
            if any(t.is_alive() and t is not threading.current_thread() for t in self.threads):
                raise RuntimeFailure('SUPERVISION_FAILED')
            if error:
                raise error
        finally:
            self._close_lock.release()
