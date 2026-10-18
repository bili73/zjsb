"""Bounded, cancellable HTTP queues; no threads or DB connections while waiting."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from time import monotonic

from .task_errors import TaskError


class Admission:
    def __init__(self, active=2, waiting=64, timeout=15, per_account=2):
        self.capacity, self.max_waiting = active, waiting
        self.timeout, self.per_account = timeout, per_account
        self.active = 0
        self.accounts = {}
        self.waiters = deque()

    def _advance(self):
        while self.waiters and self.active < self.capacity:
            waiter = self.waiters.popleft()
            if not waiter.done():
                self.active += 1
                waiter.set_result(None)

    @asynccontextmanager
    async def enter(self, account):
        if self.accounts.get(account, 0) >= self.per_account:
            raise TaskError('OPERATION_THROTTLED', '该账号已有同类操作处理中，请等待完成后再试', 429)
        if self.active >= self.capacity and len(self.waiters) >= self.max_waiting:
            raise TaskError('SERVICE_BUSY', '服务器处理队列已满，请稍后重试', 503)
        self.accounts[account] = self.accounts.get(account, 0) + 1
        started = monotonic()
        waiter = None
        acquired = False
        try:
            if self.active < self.capacity and not self.waiters:
                self.active += 1
                acquired = True
            else:
                waiter = asyncio.get_running_loop().create_future()
                self.waiters.append(waiter)
                try:
                    # Shield so cancellation cannot hide an already granted slot.
                    await asyncio.wait_for(asyncio.shield(waiter), self.timeout)
                    acquired = True
                except TimeoutError:
                    raise TaskError('SERVICE_BUSY', '服务器排队等待超时，本次操作未开始，请稍后重试', 503) from None
            yield monotonic() - started
        finally:
            if waiter is not None:
                if waiter.done() and not waiter.cancelled():
                    acquired = True
                else:
                    waiter.cancel()
                    if waiter in self.waiters:
                        self.waiters.remove(waiter)
            if acquired:
                self.active -= 1
            self.accounts[account] -= 1
            if not self.accounts[account]:
                del self.accounts[account]
            self._advance()
