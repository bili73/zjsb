import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { createMonitor } from '../src/monitor.ts'
import type { Batch, Task } from '../src/business.ts'

test('stable review-pending history is not reloaded on every active polling cycle', async () => {
  const ids = [crypto.randomUUID(), crypto.randomUUID()]
  const batches: Batch[] = ids.map(batch_id => ({ batch_id, status: 'PROCESSING', file_count: 1, updated_at: '2026-10-19T00:00:00Z' }))
  const tasks: Task[] = ids.map((batch_id, i) => ({ task_id: crypto.randomUUID(), batch_id, run_id: crypto.randomUUID(),
    result_revision: 1, status: i ? 'OCR' : 'NEED_REVIEW', cancel_requested: false, file_name: 'synthetic.png', page_count: 1, pages: [] }))
  const calls = [0, 0]
  const api = new BusinessApi(async input => {
    const path = String(input)
    if (path.includes('/batches?')) return Response.json({ items: batches, total: 2, page: 1, page_size: 50 })
    const index = ids.findIndex(id => path.includes(id))
    assert.ok(index >= 0)
    if (path.endsWith('/tasks')) { calls[index]!++; return Response.json([tasks[index]]) }
    return Response.json(batches[index])
  })
  const monitor = createMonitor(() => api)
  const signal = new AbortController().signal
  try {
    await monitor.pollOnce(signal)
    const first = [...calls]
    await monitor.pollOnce(signal)
    assert.equal(calls[0], first[0], 'review-pending history should stay cached')
    assert.equal(calls[1], first[1]! + 1, 'active tasks still refresh')
    tasks[0] = { ...tasks[0]!, result_revision: 2 }
    batches[0] = { ...batches[0]!, updated_at: '2026-10-19T00:01:00Z' }
    await monitor.pollOnce(signal)
    assert.equal(monitor.state.entries[ids[0]!]!.tasks[0]!.result_revision, 2)
    const previous = calls[0]!
    await monitor.pollOnce(signal, true)
    assert.equal(calls[0], previous + 1, 'explicit cross-session refresh still rereads history')
    monitor.state.pending[tasks[0]!.task_id] = { operation: 'rerun', task_id: tasks[0]!.task_id, run_id: tasks[0]!.run_id }
    const pendingCalls = calls[0]!
    await monitor.pollOnce(signal)
    assert.equal(calls[0], pendingCalls + 1, 'pending actions still reconcile without a timestamp change')
  } finally { monitor.dispose() }
})
