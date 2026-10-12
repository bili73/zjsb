// Central batch monitor: tracks every batch in the session at once so that
// switching upload type, tab or batch never abandons in-flight tasks. Read
// polling and write actions are fully separated — a slow upload or mutation
// never freezes status updates, unlike the retired single-selection UI.
import { reactive } from 'vue'
import { ApiFailure, canRetryRead, isAbort, retryDelay } from './api.ts'
import type { BusinessApi } from './api.ts'
import { runningStatuses } from './business.ts'
import type { Batch, Task, UploadDocType } from './business.ts'
import { ReadLoop } from './polling.ts'
import { pendingOperationText } from './workbench.ts'
import type { PendingOperation } from './workbench.ts'
import type { BatchDateRange } from './batchCalendar.ts'

export interface BatchEntry { batch: Batch | null; tasks: Task[]; tasksLoaded: boolean; expanded: boolean }
export interface MonitorState {
  entries: Record<string, BatchEntry>
  order: string[]
  serverTotal: number
  dateRange: BatchDateRange | null
  listedIds: string[]
  polling: boolean
  retrying: boolean
  failureCount: number
  lastCheckedAt: string | null
  pending: Record<string, PendingOperation>
}
export interface MonitorOptions { intervalMs?: number; pageSize?: number; isVisible?: () => boolean; onUnauthorized?: () => void }

export const entryRunning = (entry: Pick<BatchEntry, 'tasks'>) => entry.tasks.some(task => runningStatuses.has(task.status))
export const someRunning = (state: Pick<MonitorState, 'entries'>) => Object.values(state.entries).some(entryRunning)
export const entryNeedsReview = (entry: Pick<BatchEntry, 'tasks'>) => entry.tasks.some(task => task.status === 'NEED_REVIEW')

export function createMonitor(getApi: () => BusinessApi | null, options: MonitorOptions = {}) {
  const intervalMs = options.intervalMs ?? 2000
  const pageSize = options.pageSize ?? 50
  const isVisible = options.isVisible ?? (() => typeof document === 'undefined' || !document.hidden)
  const state = reactive<MonitorState>({
    entries: {}, order: [], serverTotal: 0, dateRange: null, listedIds: [], polling: false, retrying: false, failureCount: 0, lastCheckedAt: null, pending: {},
  })
  let failures = 0
  let nextPage = 2
  let listGeneration = 0
  let sessionGeneration = 0
  let disposed = false
  let unauthorizedNotified = false

  // 会话过期（401）必须把用户送回登录页，而不是当普通读取失败静默停轮询；
  // 每次登录会话只上报一次，重新登录（clear）后恢复。
  function reportUnauthorized() {
    if (unauthorizedNotified || disposed) return
    unauthorizedNotified = true
    stop()
    options.onUnauthorized?.()
  }

  function upsertBatch(batch: Batch) {
    if (disposed) return
    const existing = state.entries[batch.batch_id]
    if (existing) existing.batch = batch
    else {
      state.entries[batch.batch_id] = { batch, tasks: [], tasksLoaded: false, expanded: false }
      state.order.push(batch.batch_id)
    }
  }

  function sortBatches() {
    const stamp = (id: string) => {
      const batch = state.entries[id]?.batch
      if (!batch) return Infinity // keep accepted uploads ahead of older server snapshots
      const value = Date.parse(batch.created_at ?? '')
      return Number.isFinite(value) ? value : -Infinity
    }
    state.order = [...state.order].sort((a, b) => {
      const left = stamp(a), right = stamp(b)
      return left === right ? 0 : left > right ? -1 : 1
    })
  }

  function entryOf(taskId: string): BatchEntry | undefined {
    for (const id of state.order) {
      const entry = state.entries[id]
      if (entry?.tasks.some(task => task.task_id === taskId)) return entry
    }
    return undefined
  }

  function reconcilePending(entry: Pick<BatchEntry, 'tasks'>) {
    for (const [key, pending] of Object.entries(state.pending)) {
      if (entry.tasks.some(task => task.task_id === pending.task_id) && !pendingOperationText(pending, entry.tasks)) delete state.pending[key]
    }
  }

  function applyTasks(batchId: string, tasks: Task[]) {
    const entry = state.entries[batchId]
    if (!entry || disposed) return
    entry.tasks = tasks
    entry.tasksLoaded = true
    reconcilePending(entry)
  }

  async function pollOnce(signal: AbortSignal): Promise<number | null> {
    const client = getApi()
    if (!client || !isVisible()) return null
    const generation = listGeneration
    try {
      const list = await client.batches(1, pageSize, signal, state.dateRange)
      if (generation !== listGeneration || signal.aborted || disposed) return null
      state.serverTotal = list.total
      state.listedIds = [...new Set([...list.items.map(batch => batch.batch_id), ...state.listedIds])]
      // A batch that just left PROCESSING needs one final task fetch,
      // otherwise its rows would freeze on the last running snapshot.
      const finalized = new Set<string>()
      const policyRevision = list.items.find(batch => batch.required_fields_revision !== undefined)?.required_fields_revision
      for (const batch of list.items) {
        if (state.entries[batch.batch_id]?.batch?.status === 'PROCESSING' && batch.status !== 'PROCESSING') finalized.add(batch.batch_id)
        upsertBatch(batch)
      }
      sortBatches()
      for (const id of [...state.order]) {
        const entry = state.entries[id]
        if (!entry) continue
        // Refresh task rows for anything that can still change; terminal
        // batches keep their last known snapshot without extra requests.
        if (!entry.tasksLoaded || entry.batch?.status === 'PROCESSING' || finalized.has(id) ||
          policyRevision !== undefined && entry.tasks.some(task => task.required_fields_revision !== policyRevision)) {
          const tasks = await client.tasks(id, signal)
          if (generation !== listGeneration || signal.aborted || disposed) return null
          applyTasks(id, tasks)
        }
      }
      failures = 0
      state.failureCount = 0
      state.retrying = false
      state.lastCheckedAt = new Date().toISOString()
      return someRunning(state) ? intervalMs : null
    } catch (error) {
      if (isAbort(error) || generation !== listGeneration || disposed) return null
      if (error instanceof ApiFailure && error.card.http_status === 401) { reportUnauthorized(); return null }
      failures += 1
      state.failureCount = failures
      state.retrying = canRetryRead(error)
      return canRetryRead(error) ? retryDelay(failures) : null
    }
  }

  const loop = new ReadLoop(pollOnce)

  function start() {
    if (disposed) return
    state.polling = true
    loop.start()
  }
  function stop() {
    state.polling = false
    loop.stop()
  }
  function onVisible(visible: boolean) {
    if (disposed) return
    if (visible) start()
    else stop()
  }

  async function loadMore(signal: AbortSignal): Promise<void> {
    const client = getApi()
    if (!client) return
    const generation = listGeneration
    const list = await client.batches(nextPage, pageSize, signal, state.dateRange)
    if (generation !== listGeneration || signal.aborted || disposed) return
    nextPage += 1
    state.serverTotal = list.total
    state.listedIds = [...new Set([...state.listedIds, ...list.items.map(batch => batch.batch_id)])]
    for (const batch of list.items) upsertBatch(batch)
    sortBatches()
  }

  function setDateRange(range: BatchDateRange | null) {
    if (JSON.stringify(range) === JSON.stringify(state.dateRange)) return
    stop()
    listGeneration += 1
    state.dateRange = range
    state.listedIds = []
    state.serverTotal = 0
    nextPage = 2
    start()
  }

  async function loadTasks(batchId: string, signal: AbortSignal): Promise<void> {
    const client = getApi()
    if (!client) return
    const generation = listGeneration
    const tasks = await client.tasks(batchId, signal)
    if (generation === listGeneration && !signal.aborted) applyTasks(batchId, tasks)
  }

  function setExpanded(batchId: string, expanded: boolean) {
    const entry = state.entries[batchId]
    if (!entry) return
    entry.expanded = expanded
    if (expanded && !entry.tasksLoaded) {
      const generation = sessionGeneration
      const controller = new AbortController()
      void loadTasks(batchId, controller.signal).catch(error => {
        if (generation !== sessionGeneration || disposed) return
        entry.tasksLoaded = false
        // 该读取路径不在轮询循环内；会话过期同样必须把用户送回登录页。
        if (error instanceof ApiFailure && error.card.http_status === 401) reportUnauthorized()
      })
    }
  }

  async function submitUpload(files: readonly File[], docType: UploadDocType, abnormalOnly: boolean, signal: AbortSignal): Promise<{ batch_id: string; task_ids: string[] }> {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const created = await client.upload(files, docType, abnormalOnly, signal)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return created
    if (!state.entries[created.batch_id]) {
      state.entries[created.batch_id] = { batch: null, tasks: [], tasksLoaded: false, expanded: true }
      state.order.unshift(created.batch_id)
    }
    start()
    return created
  }

  async function runAction(operation: 'cancel' | 'rerun', batchId: string, task: Task, signal: AbortSignal): Promise<Task> {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const updated = await client.mutate(task, operation, signal)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return updated
    const entry = state.entries[batchId]
    if (entry) {
      entry.tasks = entry.tasks.map(item => item.task_id === updated.task_id ? updated : item)
      reconcilePending(entry)
    }
    state.pending[updated.task_id] = { operation, task_id: updated.task_id, run_id: updated.run_id }
    start()
    return updated
  }

  async function deleteBatch(batchId: string, tasks: readonly Task[], signal: AbortSignal) {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const result = await client.deleteBatch(batchId, tasks, signal)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return result
    // Invalidate pre-deletion list/task reads before removing cached entries.
    stop()
    listGeneration++
    const wasListed = state.listedIds.includes(batchId)
    delete state.entries[batchId]
    state.order = state.order.filter(id => id !== batchId)
    state.listedIds = state.listedIds.filter(id => id !== batchId)
    if (wasListed) state.serverTotal = Math.max(0, state.serverTotal - 1)
    for (const id of result.task_ids) delete state.pending[id]
    nextPage = 2 // Deletion shifts server pages; reread page two rather than skip rows.
    start()
    return result
  }

  function pendingNotice(taskId: string): string {
    const pending = state.pending[taskId]
    if (!pending) return ''
    return pendingOperationText(pending, entryOf(taskId)?.tasks ?? [])
  }

  function clear() {
    stop()
    sessionGeneration++
    state.entries = {}
    state.order = []
    state.serverTotal = 0
    state.dateRange = null
    state.listedIds = []
    listGeneration += 1
    state.pending = {}
    state.failureCount = 0
    state.retrying = false
    state.lastCheckedAt = null
    failures = 0
    nextPage = 2
    unauthorizedNotified = false
  }

  function dispose() { disposed = true; clear() }

  return { state, pollOnce, start, stop, onVisible, loadMore, loadTasks, setDateRange, setExpanded, submitUpload, runAction, deleteBatch, pendingNotice, entryOf, clear, dispose }
}
export type Monitor = ReturnType<typeof createMonitor>
