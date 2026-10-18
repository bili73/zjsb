import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { createMonitor } from '../src/monitor.ts'
import type { Batch, Task } from '../src/business.ts'

const batchId = (index: number) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`

function fixture() {
  const batches: Batch[] = Array.from({ length: 41 }, (_, index) => ({
    batch_id: batchId(index), status: index === 0 ? 'PROCESSING' : 'COMPLETED',
    created_at: '2026-10-16T00:00:00Z', file_count: 1,
  }))
  const tasks = new Map<string, Task[]>(batches.map((b, i) => [b.batch_id, [{
    task_id: crypto.randomUUID(), batch_id: b.batch_id, run_id: crypto.randomUUID(), result_revision: 4,
    cancel_requested: false, status: i === 0 ? 'OCR' : 'COMPLETED', file_name: 'synthetic.png',
    doc_type: 'DIPLOMA', page_count: 1, pages: [],
  }]]))
  const state = { calls: [] as number[], failPage: 0, delayPage: 0,
    pending: undefined as undefined | { enter: () => void; promise: Promise<void> } }
  const api = new BusinessApi(async (input, init) => {
    const url = new URL(String(input), 'http://fixture')
    if (url.pathname === '/api/v1/batches') {
      if (init?.method === 'POST') {
        const id = batchId(99), taskId = crypto.randomUUID()
        batches.unshift({ batch_id: id, status: 'PROCESSING', file_count: 1 })
        tasks.set(id, [{ ...tasks.get(batchId(0))![0]!, task_id: taskId, batch_id: id }])
        return Response.json({ batch_id: id, task_ids: [taskId] }, { status: 202 })
      }
      const page = Number(url.searchParams.get('page')), size = Number(url.searchParams.get('page_size'))
      state.calls.push(page)
      if (state.failPage === page) throw new TypeError('synthetic network failure')
      const body = { items: batches.slice((page - 1) * size, page * size), total: batches.length, page, page_size: size }
      if (state.delayPage === page && state.pending) { state.pending.enter(); await state.pending.promise }
      return Response.json(body)
    }
    const id = url.pathname.split('/batches/')[1]!.split('/')[0]!
    if (init?.method === 'DELETE') {
      const index = batches.findIndex(b => b.batch_id === id)
      if (index >= 0) batches.splice(index, 1)
      return Response.json({ batch_id: id, task_ids: (tasks.get(id) ?? []).map(t => t.task_id), cleanup_pending: false })
    }
    if (url.pathname.endsWith('/tasks')) return Response.json(tasks.get(id) ?? [])
    return Response.json(batches.find(b => b.batch_id === id))
  })
  const monitor = createMonitor(() => api, { pageSize: 20, intervalMs: 10000, isVisible: () => true })
  return { batches, tasks, state, monitor, signal: new AbortController().signal }
}

test('direct page jump keeps only that page visible while hidden active tasks and revisions survive', async () => {
  const { monitor, state, tasks, signal } = fixture()
  try {
    await monitor.pollOnce(signal)
    monitor.setExpanded(batchId(0), true)
    await monitor.changePage(3, signal)
    monitor.stop()
    assert.deepEqual(state.calls, [1, 3])
    assert.deepEqual(monitor.state.listedIds, [batchId(40)])
    assert.equal(monitor.state.entries[batchId(0)]!.expanded, true)
    assert.equal(monitor.state.entries[batchId(0)]!.tasks[0]!.result_revision, 4)
    tasks.get(batchId(0))![0] = { ...tasks.get(batchId(0))![0]!, status: 'EXTRACTING' }
    await monitor.pollOnce(signal)
    assert.deepEqual(monitor.state.listedIds, [batchId(40)])
    assert.equal(monitor.state.entries[batchId(0)]!.tasks[0]!.status, 'EXTRACTING')
    await monitor.changePage(1, signal, 50)
    assert.equal(monitor.state.pageSize, 50)
    assert.equal(monitor.state.page, 1)
    assert.equal(monitor.state.listedIds.length, 41)
  } finally { monitor.dispose() }
})

test('failed page jump retains the last page and cached results', async () => {
  const { monitor, state, signal } = fixture()
  try {
    await monitor.pollOnce(signal)
    const ids = [...monitor.state.listedIds]
    state.failPage = 3
    await assert.rejects(monitor.changePage(3, signal))
    monitor.stop()
    assert.equal(monitor.state.page, 1)
    assert.deepEqual(monitor.state.listedIds, ids)
    assert.equal(monitor.state.entries[batchId(0)]!.tasks[0]!.result_revision, 4)
  } finally { monitor.dispose() }
})

test('shrinking totals correct the current page once rather than leaving an empty last page', async () => {
  const { monitor, batches, state, signal } = fixture()
  try {
    await monitor.changePage(3, signal); monitor.stop()
    batches.pop()
    state.calls = []
    await monitor.pollOnce(signal)
    assert.deepEqual(state.calls, [3, 2])
    assert.equal(monitor.state.page, 2)
    assert.equal(monitor.state.serverTotal, 40)
    assert.equal(monitor.state.listedIds.length, 20)
  } finally { monitor.dispose() }
})

test('deleting the last batch on a page moves to the previous page and retains other jobs', async () => {
  const { monitor, tasks, signal } = fixture()
  try {
    await monitor.pollOnce(signal)
    await monitor.changePage(3, signal); monitor.stop()
    await monitor.deleteBatch(batchId(40), tasks.get(batchId(40))!, signal); monitor.stop()
    await monitor.pollOnce(signal)
    assert.equal(monitor.state.page, 2)
    assert.equal(monitor.state.listedIds.length, 20)
    assert.equal(monitor.state.entries[batchId(40)], undefined)
    assert.equal(monitor.state.entries[batchId(0)]!.tasks[0]!.status, 'OCR')
  } finally { monitor.dispose() }
})

test('late page responses cannot overwrite a changed date range or another account', async () => {
  for (const action of ['date', 'account'] as const) {
    const { monitor, state, signal } = fixture()
    const enter = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
    try {
      await monitor.pollOnce(signal)
      state.delayPage = 3; state.pending = { enter: enter.resolve, promise: release.promise }
      const pending = monitor.changePage(3, signal)
      await enter.promise
      if (action === 'date') { monitor.setDateRange({ date_from: '2026-10-16', date_to: '2026-10-16' }); monitor.stop(); await monitor.pollOnce(signal) }
      else monitor.clear()
      release.resolve(); await pending
      assert.equal(monitor.state.page, 1)
      assert.equal(monitor.state.entries[batchId(40)], undefined)
      if (action === 'account') { assert.equal(monitor.state.order.length, 0); assert.equal(monitor.state.serverTotal, 0) }
      else assert.deepEqual(monitor.state.listedIds, Array.from({ length: 20 }, (_, i) => batchId(i)))
    } finally { release.resolve(); monitor.dispose() }
  }
})

test('an upload accepted during a historical page request remains on the first page', async () => {
  const { monitor, state, signal } = fixture()
  const enter = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
  try {
    await monitor.pollOnce(signal)
    state.delayPage = 3; state.pending = { enter: enter.resolve, promise: release.promise }
    const pending = monitor.changePage(3, signal)
    await enter.promise
    await monitor.submitUpload([new File(['synthetic'], 'sample.png')], 'DIPLOMA', false, signal)
    monitor.stop()
    release.resolve(); await pending
    assert.equal(monitor.state.page, 1)
    assert.ok(monitor.state.listedIds.includes(batchId(99)))
    assert.ok(!monitor.state.listedIds.includes(batchId(40)))
    assert.equal(monitor.state.entries[batchId(99)]!.expanded, true)
  } finally { release.resolve(); monitor.dispose() }
})
