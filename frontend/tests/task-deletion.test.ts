import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiFailure, BusinessApi } from '../src/api.ts'
import { createMonitor } from '../src/monitor.ts'
import type { Task } from '../src/business.ts'

const batchId = '11111111-2222-4333-8444-555555555555'
const task = (): Task => ({ task_id: crypto.randomUUID(), batch_id: batchId, run_id: crypto.randomUUID(),
  result_revision: 2, status: 'NEED_REVIEW', doc_type: 'DIPLOMA', file_name: 'synthetic.png',
  page_count: 1, cancel_requested: false, pages: [] })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })

test('deleting a task retains peer jobs, clears its pending state and refreshes package metadata', async () => {
  const first = task(), peer = { ...task(), status: 'OCR' as const }
  let tasks = [first, peer], revision = 0
  const client = new BusinessApi(async (input, init) => {
    const url = String(input)
    if (init?.method === 'DELETE') {
      assert.deepEqual(JSON.parse(String(init.body)), { run_id: first.run_id, expected_revision: 2 })
      tasks = [peer]; revision++
      return json({ task_id: first.task_id, batch_id: batchId, batch_deleted: false, cleanup_pending: false })
    }
    if (url.endsWith('/tasks')) return json(tasks)
    const batch = { batch_id: batchId, created_at: '2026-10-19T01:00:00Z', status: 'PROCESSING',
      file_count: tasks.length, package_revision: revision }
    return url.includes('?') ? json({ items: [batch], total: 1, page: 1, page_size: 50 }) : json(batch)
  })
  const monitor = createMonitor(() => client), signal = new AbortController().signal
  try {
    await monitor.pollOnce(signal)
    monitor.state.pending[first.task_id] = { operation: 'cancel', task_id: first.task_id, run_id: first.run_id }
    await monitor.deleteTask(batchId, first, signal); monitor.stop()
    assert.deepEqual(monitor.state.entries[batchId]!.tasks.map(t => t.task_id), [peer.task_id])
    assert.equal(monitor.state.pending[first.task_id], undefined)
    assert.equal(monitor.state.serverTotal, 1)
    await monitor.pollOnce(signal)
    assert.equal(monitor.state.entries[batchId]!.batch!.package_revision, 1)
    assert.equal(monitor.state.entries[batchId]!.batch!.file_count, 1)
  } finally { monitor.dispose() }
})

test('last-task deletion removes its empty batch and preserves the current filter', async () => {
  const original = task()
  const client = new BusinessApi(async () => json({ task_id: original.task_id, batch_id: batchId,
    batch_deleted: true, cleanup_pending: true }))
  const monitor = createMonitor(() => client, { isVisible: () => false })
  try {
    monitor.state.entries[batchId] = { batch: null, tasks: [original], tasksLoaded: true, expanded: true }
    monitor.state.order = [batchId]; monitor.state.listedIds = [batchId]; monitor.state.serverTotal = 1
    monitor.state.dateRange = { date_from: '2026-10-19', date_to: '2026-10-19' }
    const result = await monitor.deleteTask(batchId, original, new AbortController().signal)
    assert.equal(result.cleanup_pending, true)
    assert.equal(monitor.state.entries[batchId], undefined)
    assert.equal(monitor.state.serverTotal, 0)
    assert.deepEqual(monitor.state.order, [])
    assert.equal(monitor.state.dateRange.date_from, '2026-10-19')
  } finally { monitor.dispose() }
})

test('a pre-deletion task read cannot restore the deleted task', async () => {
  const first = task(), peer = task()
  let release: (() => void) | undefined
  const client = new BusinessApi(async (_input, init) => {
    if (init?.method === 'DELETE') return json({ task_id: first.task_id, batch_id: batchId,
      batch_deleted: false, cleanup_pending: false })
    const response = json([first, peer])
    await new Promise<void>(resolve => { release = resolve })
    return response
  })
  const monitor = createMonitor(() => client, { isVisible: () => false }), signal = new AbortController().signal
  try {
    monitor.state.entries[batchId] = { batch: null, tasks: [first, peer], tasksLoaded: true, expanded: true }
    const stale = monitor.loadTasks(batchId, signal)
    while (!release) await new Promise(resolve => setTimeout(resolve, 0))
    await monitor.deleteTask(batchId, first, signal)
    release(); await stale
    assert.deepEqual(monitor.state.entries[batchId]!.tasks.map(t => t.task_id), [peer.task_id])
  } finally { release?.(); monitor.dispose() }
})

test('conflict keeps cached corrections and a late response cannot change a newer session', async () => {
  for (const status of [409, 200]) {
    const original = task()
    let release: (() => void) | undefined
    const client = new BusinessApi(async () => {
      await new Promise<void>(resolve => { release = resolve })
      return status === 409 ? json({ code: 'RESULT_VERSION_CONFLICT' }, status) :
        json({ task_id: original.task_id, batch_id: batchId, batch_deleted: true, cleanup_pending: false })
    })
    const monitor = createMonitor(() => client, { isVisible: () => false })
    try {
      monitor.state.entries[batchId] = { batch: null, tasks: [original], tasksLoaded: true, expanded: true }
      const pending = monitor.deleteTask(batchId, original, new AbortController().signal)
      while (!release) await new Promise(resolve => setTimeout(resolve, 0))
      if (status === 200) {
        monitor.clear()
        monitor.state.entries[batchId] = { batch: null, tasks: [original], tasksLoaded: true, expanded: true }
      }
      release()
      if (status === 409) await assert.rejects(pending, ApiFailure)
      else await pending
      assert.equal(monitor.state.entries[batchId]!.tasks[0]!.task_id, original.task_id)
    } finally { release?.(); monitor.dispose() }
  }
})

test('task deletion rejects a response belonging to a different task or batch', async () => {
  const original = task()
  for (const override of [{ task_id: crypto.randomUUID() }, { batch_id: crypto.randomUUID() }, { batch_deleted: 1 }]) {
    const api = new BusinessApi(async () => json({ task_id: original.task_id, batch_id: batchId,
      batch_deleted: true, cleanup_pending: false, ...override }))
    await assert.rejects(api.deleteTask(batchId, original, new AbortController().signal), ApiFailure)
  }
})
