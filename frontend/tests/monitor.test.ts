// Concurrency regression suite: switching document types mid-flight must never
// drop or freeze the batches already uploaded.
import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { createMonitor, someRunning } from '../src/monitor.ts'
import type { Batch, Task } from '../src/business.ts'
import { formatTime } from '../src/presentation.ts'

const mkBatch = (id: string, status: Batch['status'] = 'PROCESSING'): Batch =>
  ({ batch_id: id, status, file_count: 1, created_at: '2026-10-08T10:00:00Z' })

const mkTask = (id: string, batchId: string, status: Task['status'], docType: string): Task =>
  ({ task_id: id, batch_id: batchId, run_id: crypto.randomUUID(), result_revision: 1, cancel_requested: false, status, file_name: 'a.pdf', doc_type: docType, page_count: 1, pages: [] })

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json', 'X-Request-ID': 'e_monitor1' },
})

function makeServer() {
  const db = {
    batches: [] as Batch[], tasks: {} as Record<string, Task[]>, page2: [] as Batch[], failNextList: 0, lastAbnormalOnly: '', listQueries: [] as string[],
  }
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/batches?')) {
      if (db.failNextList > 0) { db.failNextList -= 1; throw new TypeError('network down') }
      const query = new URL(url, 'http://localhost').searchParams
      db.listQueries.push(query.toString())
      const page = Number(query.get('page') ?? '1')
      const inRange = (batch: Batch) => {
        const day = formatTime(batch.created_at).slice(0, 10)
        return (!query.get('date_from') || day >= query.get('date_from')!) && (!query.get('date_to') || day <= query.get('date_to')!)
      }
      const items = (page === 1 ? db.batches : db.page2).filter(inRange)
      return json({ items, total: [...db.batches, ...db.page2].filter(inRange).length, page, page_size: 50 })
    }
    if (url.includes('/batches/') && url.includes('/tasks')) {
      const batchId = url.split('/batches/')[1]!.split('/tasks')[0]
      return json(db.tasks[batchId] ?? [])
    }
    if (url.includes('/batches') && method === 'POST') {
      const form = init?.body as FormData
      const files = form.getAll('files') as File[]
      const docType = String(form.get('doc_type_hint'))
      db.lastAbnormalOnly = String(form.get('abnormal_only'))
      const batchId = crypto.randomUUID()
      db.batches.unshift(mkBatch(batchId))
      db.tasks[batchId] = files.map(file => mkTask(crypto.randomUUID(), batchId, 'QUEUED', docType))
      return json({ batch_id: batchId, task_ids: db.tasks[batchId].map(t => t.task_id) }, 201)
    }
    if (url.endsWith('/cancel') || url.endsWith('/rerun')) {
      const taskId = url.split('/tasks/')[1]!.split('/')[0]
      for (const list of Object.values(db.tasks)) {
        const index = list.findIndex(t => t.task_id === taskId)
        if (index >= 0) {
          const current = list[index]!
          const updated = url.endsWith('/cancel')
            ? { ...current, cancel_requested: true }
            : { ...current, run_id: crypto.randomUUID(), status: 'QUEUED', result_revision: current.result_revision + 1 }
          list[index] = updated
          return json(updated)
        }
      }
    }
    throw new TypeError(`unmatched ${method} ${url}`)
  }
  return { db, fetcher }
}

function makeMonitorCase() {
  const server = makeServer()
  const client = new BusinessApi(server.fetcher)
  const monitor = createMonitor(() => client, { intervalMs: 15, isVisible: () => true })
  const signal = () => new AbortController().signal
  return { server, monitor, signal }
}

const pdf = (name: string) => new File(['%PDF-1.4 fake'], name, { type: 'application/pdf' })

test('first refresh and merged pages remain descending without losing optimistic uploads', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const newest = { ...mkBatch(crypto.randomUUID(), 'COMPLETED'), created_at: '2026-10-08T11:00:00Z' }
    const older = { ...mkBatch(crypto.randomUUID(), 'COMPLETED'), created_at: '2026-10-08T09:00:00Z' }
    server.db.batches = [newest, older]
    await monitor.pollOnce(signal())
    assert.deepEqual(monitor.state.order, [newest.batch_id, older.batch_id])
    const pending = await monitor.submitUpload([pdf('new.pdf')], 'DIPLOMA', false, signal())
    monitor.stop()
    server.db.batches = [newest, older] // newly accepted upload not yet present in list snapshot
    const middle = { ...mkBatch(crypto.randomUUID(), 'COMPLETED'), created_at: '2026-10-08T10:00:00Z' }
    server.db.page2 = [middle, older]
    await monitor.loadMore(signal())
    await monitor.pollOnce(signal())
    assert.deepEqual(monitor.state.order, [pending.batch_id, newest.batch_id, middle.batch_id, older.batch_id])
    assert.ok(monitor.state.entries[newest.batch_id]?.tasksLoaded)
  } finally { monitor.dispose() }
})

test('calendar filtering preserves hidden running tasks and resets server pagination', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  const old = { ...mkBatch(crypto.randomUUID()), created_at: '2026-10-07T17:00:00Z' }
  const today = { ...mkBatch(crypto.randomUUID(), 'COMPLETED'), created_at: '2026-10-08T17:00:00Z' }
  server.db.batches = [today, old]
  const running = mkTask(crypto.randomUUID(), old.batch_id, 'OCR', 'MEDICAL_REPORT')
  server.db.tasks[old.batch_id] = [running]
  try {
    await monitor.pollOnce(signal())
    await monitor.loadMore(signal())
    monitor.setDateRange({ date_from: '2026-10-09', date_to: '2026-10-09' }); monitor.stop()
    await monitor.pollOnce(signal())
    assert.deepEqual(monitor.state.listedIds, [today.batch_id])
    assert.equal(monitor.state.serverTotal, 1)
    assert.ok(monitor.state.order.includes(old.batch_id))
    assert.equal(someRunning(monitor.state), true)
    server.db.tasks[old.batch_id] = [{ ...running, status: 'NEED_REVIEW' }]
    await monitor.pollOnce(signal())
    assert.equal(monitor.state.entries[old.batch_id]!.tasks[0]!.status, 'NEED_REVIEW')
    await monitor.loadMore(signal())
    const query = new URLSearchParams(server.db.listQueries.at(-1))
    assert.equal(query.get('page'), '2')
    assert.equal(query.get('date_from'), '2026-10-09')
    monitor.clear()
    assert.equal(monitor.state.dateRange, null)
    assert.deepEqual(monitor.state.listedIds, [])
  } finally { monitor.dispose() }
})

test('an old calendar page response cannot replace the newly selected range', async () => {
  const old = mkBatch(crypto.randomUUID(), 'COMPLETED'), current = mkBatch(crypto.randomUUID(), 'COMPLETED')
  let release: ((response: Response) => void) | undefined
  const client = new BusinessApi(async input => {
    const url = new URL(String(input), 'http://localhost')
    if (url.pathname.endsWith('/tasks')) return json([])
    if (url.searchParams.get('page') === '2' && !url.searchParams.has('date_from')) return new Promise<Response>(resolve => { release = resolve })
    return json({ items: [current], total: 1, page: 1, page_size: 50 })
  })
  const monitor = createMonitor(() => client)
  try {
    const late = monitor.loadMore(new AbortController().signal)
    monitor.setDateRange({ date_from: '2026-10-09', date_to: '2026-10-09' }); monitor.stop()
    await monitor.pollOnce(new AbortController().signal)
    release!(json({ items: [old], total: 100, page: 2, page_size: 50 }))
    await late
    assert.deepEqual(monitor.state.listedIds, [current.batch_id])
    assert.equal(monitor.state.serverTotal, 1)
    assert.equal(monitor.state.entries[old.batch_id], undefined)
  } finally { monitor.dispose() }
})

test('switching document type keeps earlier batches and keeps polling', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const medical = await monitor.submitUpload([pdf('report.pdf')], 'MEDICAL_REPORT', true, signal())
    monitor.stop()
    assert.equal(server.db.lastAbnormalOnly, 'true')
    let delay = await monitor.pollOnce(signal())
    assert.equal(delay, 15)
    assert.equal(monitor.state.entries[medical.batch_id]?.tasks[0]?.status, 'QUEUED')

    // 第一个批次进行中时切换类型提交第二个批次。
    server.db.tasks[medical.batch_id]![0]!.status = 'OCR'
    const diploma = await monitor.submitUpload([pdf('diploma.pdf')], 'DIPLOMA', false, signal())
    monitor.stop()
    assert.equal(monitor.state.order.length, 2)
    assert.equal(monitor.state.entries[medical.batch_id]?.batch?.status, 'PROCESSING')

    delay = await monitor.pollOnce(signal())
    assert.equal(delay, 15)
    assert.equal(monitor.state.entries[diploma.batch_id]?.tasks[0]?.status, 'QUEUED')
    assert.equal(someRunning(monitor.state), true)

    // 医疗批次完成、学位批次仍在跑：已完成的任务快照必须保留。
    server.db.tasks[medical.batch_id] = server.db.tasks[medical.batch_id]!.map(t => ({ ...t, status: 'COMPLETED' as const }))
    server.db.batches[server.db.batches.findIndex(b => b.batch_id === medical.batch_id)] = mkBatch(medical.batch_id, 'COMPLETED')
    server.db.tasks[diploma.batch_id]![0]!.status = 'EXTRACTING'
    delay = await monitor.pollOnce(signal())
    assert.equal(delay, 15)
    assert.equal(monitor.state.entries[medical.batch_id]?.tasks[0]?.status, 'COMPLETED')
    assert.equal(monitor.state.entries[diploma.batch_id]?.tasks[0]?.status, 'EXTRACTING')

    // 全部结束后轮询自行停止。
    server.db.tasks[diploma.batch_id] = server.db.tasks[diploma.batch_id]!.map(t => ({ ...t, status: 'COMPLETED' as const }))
    delay = await monitor.pollOnce(signal())
    assert.equal(delay, null)
    assert.equal(someRunning(monitor.state), false)
  } finally {
    monitor.dispose()
  }
})

test('submitUpload inserts an optimistic entry before the list catches up', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const created = await monitor.submitUpload([pdf('a.pdf')], 'DEGREE_CERT', false, signal())
    monitor.stop()
    assert.equal(server.db.lastAbnormalOnly, 'false')
    const entry = monitor.state.entries[created.batch_id]
    assert.ok(entry)
    assert.equal(entry.batch, null)
    assert.equal(entry.expanded, true)
    assert.equal(monitor.state.order[0], created.batch_id)
  } finally {
    monitor.dispose()
  }
})

test('cancel notices appear on request and clear once the server confirms', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const created = await monitor.submitUpload([pdf('a.pdf')], 'MEDICAL_REPORT', false, signal())
    monitor.stop()
    await monitor.pollOnce(signal())
    const target = monitor.state.entries[created.batch_id]!.tasks[0]!
    const updated = await monitor.runAction('cancel', created.batch_id, target, signal())
    assert.equal(updated.cancel_requested, true)
    assert.match(monitor.pendingNotice(target.task_id), /等待服务确认/)

    server.db.tasks[created.batch_id] = server.db.tasks[created.batch_id]!.map(t => ({ ...t, status: 'CANCELLED' as const }))
    await monitor.pollOnce(signal())
    assert.equal(monitor.pendingNotice(target.task_id), '')
    assert.equal(monitor.state.entries[created.batch_id]!.tasks[0]?.status, 'CANCELLED')
  } finally {
    monitor.dispose()
  }
})

test('rerun swaps the task row and reports the queued follow-up', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const created = await monitor.submitUpload([pdf('a.pdf')], 'DIPLOMA', false, signal())
    monitor.stop()
    await monitor.pollOnce(signal())
    server.db.tasks[created.batch_id] = server.db.tasks[created.batch_id]!.map(t => ({ ...t, status: 'FAILED' as const }))
    await monitor.pollOnce(signal())
    const failed = monitor.state.entries[created.batch_id]!.tasks[0]!
    assert.equal(failed.status, 'FAILED')

    const updated = await monitor.runAction('rerun', created.batch_id, failed, signal())
    assert.equal(updated.status, 'QUEUED')
    assert.notEqual(updated.run_id, failed.run_id)
    assert.match(monitor.pendingNotice(updated.task_id), /排队/)
  } finally {
    monitor.dispose()
  }
})

test('read failures back off and recover without losing tracked batches', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const created = await monitor.submitUpload([pdf('a.pdf')], 'MEDICAL_REPORT', false, signal())
    monitor.stop()
    await monitor.pollOnce(signal())

    server.db.failNextList = 1
    const delay = await monitor.pollOnce(signal())
    assert.equal(delay, 2000)
    assert.equal(monitor.state.failureCount, 1)
    assert.equal(monitor.state.retrying, true)
    assert.ok(monitor.state.entries[created.batch_id])

    const recovered = await monitor.pollOnce(signal())
    assert.equal(recovered, 15)
    assert.equal(monitor.state.failureCount, 0)
    assert.equal(monitor.state.retrying, false)
  } finally {
    monitor.dispose()
  }
})

test('loadMore appends older pages while keeping newest-first order', async () => {
  const { server, monitor, signal } = makeMonitorCase()
  try {
    const created = await monitor.submitUpload([pdf('new.pdf')], 'DIPLOMA', false, signal())
    monitor.stop()
    await monitor.pollOnce(signal())
    const older = crypto.randomUUID()
    server.db.page2 = [mkBatch(older, 'COMPLETED')]

    await monitor.loadMore(signal())
    assert.equal(monitor.state.order[0], created.batch_id)
    assert.ok(monitor.state.order.includes(older))
    assert.equal(monitor.state.serverTotal, 2)
  } finally {
    monitor.dispose()
  }
})

test('session expiry reports unauthorized once, stops polling and keeps batches for relogin', async () => {
  let expired = false
  let unauthorizedCount = 0
  const batchId = crypto.randomUUID()
  const fetcher: typeof fetch = (async (input, init) => {
    const url = String(input)
    if (url.includes('/batches?')) {
      if (expired) return new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED' } }), { status: 401, headers: { 'content-type': 'application/json' } })
      return json({ items: [mkBatch(batchId, 'PROCESSING')], total: 1, page: 1, page_size: 50 })
    }
    if (url.includes('/tasks')) return json([mkTask(crypto.randomUUID(), batchId, 'QUEUED', 'DIPLOMA')])
    throw new TypeError(`unmatched ${init?.method ?? 'GET'} ${url}`)
  }) as typeof fetch
  const client = new BusinessApi(fetcher)
  const monitor = createMonitor(() => client, { intervalMs: 15, isVisible: () => true, onUnauthorized: () => { unauthorizedCount += 1 } })
  try {
    const signal = () => new AbortController().signal
    assert.equal(await monitor.pollOnce(signal()), 15)
    assert.ok(monitor.state.entries[batchId])

    // 会话过期：不再退避，直接停轮询并上报一次；已上传批次保留在内存里。
    expired = true
    assert.equal(await monitor.pollOnce(signal()), null)
    assert.equal(unauthorizedCount, 1)
    assert.equal(monitor.state.failureCount, 0)
    assert.ok(monitor.state.entries[batchId])
    await monitor.pollOnce(signal())
    assert.equal(unauthorizedCount, 1)

    // 重新登录（clear）后恢复上报能力。
    monitor.clear()
    assert.equal(await monitor.pollOnce(signal()), null)
    assert.equal(unauthorizedCount, 2)
  } finally { monitor.dispose() }
})

test('expanding a batch after session expiry reports unauthorized instead of failing silently', async () => {
  let expired = false
  let unauthorizedCount = 0
  const batchId = crypto.randomUUID()
  const fetcher: typeof fetch = (async input => {
    const url = String(input)
    if (url.includes('/batches?')) return json({ items: [mkBatch(batchId, 'COMPLETED')], total: 1, page: 1, page_size: 50 })
    if (url.includes('/tasks')) {
      if (expired) return new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED' } }), { status: 401, headers: { 'content-type': 'application/json' } })
      return json([mkTask(crypto.randomUUID(), batchId, 'COMPLETED', 'DIPLOMA')])
    }
    throw new TypeError(`unmatched ${String(input)}`)
  }) as typeof fetch
  const client = new BusinessApi(fetcher)
  const monitor = createMonitor(() => client, { intervalMs: 15, isVisible: () => true, onUnauthorized: () => { unauthorizedCount += 1 } })
  try {
    const signal = () => new AbortController().signal
    await monitor.pollOnce(signal())
    assert.ok(monitor.state.entries[batchId]?.tasksLoaded)

    // 轮询自停后（全部终态）会话过期；此时手动展开任务列表，401 不得被静默吞掉。
    expired = true
    monitor.state.entries[batchId]!.tasksLoaded = false
    monitor.setExpanded(batchId, true)
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.equal(unauthorizedCount, 1)
    assert.equal(monitor.state.entries[batchId]?.tasksLoaded, false)
  } finally { monitor.dispose() }
})

test('clear resets everything for the next session', async () => {
  const { monitor, signal } = makeMonitorCase()
  try {
    await monitor.submitUpload([pdf('a.pdf')], 'MEDICAL_REPORT', false, signal())
    monitor.stop()
    monitor.clear()
    assert.equal(monitor.state.order.length, 0)
    assert.equal(monitor.state.polling, false)
    assert.equal(monitor.state.lastCheckedAt, null)
    monitor.dispose()
    // dispose 后任何写入都应被忽略，避免会话间串数据。
    const late = await monitor.submitUpload([pdf('late.pdf')], 'DIPLOMA', false, signal()).then(() => 'ok', () => 'fail')
    assert.equal(late, 'ok')
    assert.equal(monitor.state.order.length, 0)
  } finally {
    monitor.dispose()
  }
})
