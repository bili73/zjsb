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
  page: number
  pageSize: number
  polling: boolean
  retrying: boolean
  failureCount: number
  lastCheckedAt: string | null
  pending: Record<string, PendingOperation>
}
export interface MonitorOptions {
  intervalMs?: number
  pageSize?: number
  isVisible?: () => boolean
  onUnauthorized?: () => void
  onBatchRemoved?: (batchId: string, taskIds: string[]) => void
}

export const entryRunning = (entry: Pick<BatchEntry, 'tasks'>) => entry.tasks.some(task => runningStatuses.has(task.status))
export const someRunning = (state: Pick<MonitorState, 'entries'>) => Object.values(state.entries).some(entryRunning)
export const entryNeedsReview = (entry: Pick<BatchEntry, 'tasks'>) => entry.tasks.some(task => task.status === 'NEED_REVIEW')

export function createMonitor(getApi: () => BusinessApi | null, options: MonitorOptions = {}) {
  const intervalMs = options.intervalMs ?? 2000
  const initialPageSize = options.pageSize ?? 50
  const isVisible = options.isVisible ?? (() => typeof document === 'undefined' || !document.hidden)
  const state = reactive<MonitorState>({
    entries: {}, order: [], serverTotal: 0, dateRange: null, listedIds: [], page: 1, pageSize: initialPageSize,
    polling: false, retrying: false, failureCount: 0, lastCheckedAt: null, pending: {},
  })
  let failures = 0
  let listGeneration = 0
  let sessionGeneration = 0
  let disposed = false
  let unauthorizedNotified = false
  let refreshRequested = false
  const taskRefreshNeeded = new Set<string>()

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
    if (existing) {
      if (existing.batch?.status !== batch.status || existing.batch?.updated_at !== batch.updated_at ||
          existing.batch?.package_revision !== batch.package_revision) taskRefreshNeeded.add(batch.batch_id)
      existing.batch = batch
    }
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

  function removeBatch(batchId: string, taskIds: readonly string[]) {
    taskRefreshNeeded.delete(batchId)
    delete state.entries[batchId]
    state.order = state.order.filter(id => id !== batchId)
    state.listedIds = state.listedIds.filter(id => id !== batchId)
    for (const id of taskIds) delete state.pending[id]
  }

  async function pollOnce(signal: AbortSignal, refreshTasks = false): Promise<number | null> {
    const client = getApi()
    if (!client || !isVisible()) return null
    const generation = listGeneration
    if (refreshTasks) state.order.forEach(id => taskRefreshNeeded.add(id))
    try {
      let list = await client.batches(state.page, state.pageSize, signal, state.dateRange)
      if (generation !== listGeneration || signal.aborted || disposed) return null
      const last = Math.max(1, Math.ceil(list.total / state.pageSize))
      if (state.page > last) list = await client.batches(last, state.pageSize, signal, state.dateRange)
      if (generation !== listGeneration || signal.aborted || disposed) return null
      state.page = list.page
      state.serverTotal = list.total
      state.listedIds = list.items.map(batch => batch.batch_id)
      const policyRevision = list.items.find(batch => batch.required_fields_revision !== undefined)?.required_fields_revision
      for (const batch of list.items) {
        upsertBatch(batch)
      }
      sortBatches()
      const listedBatchIds = new Set(list.items.map(batch => batch.batch_id))
      let removed = false
      for (const id of [...state.order]) {
        const entry = state.entries[id]
        if (!entry) continue
        // Explicit reconciliation also rereads terminal batches on older pages.
        if (taskRefreshNeeded.has(id) || !entry.tasksLoaded || entryRunning(entry) ||
          entry.batch?.status === 'PROCESSING' && !entry.batch.updated_at ||
          entry.tasks.some(task => state.pending[task.task_id]) ||
          policyRevision !== undefined && entry.tasks.some(task => task.required_fields_revision !== policyRevision)) {
          try {
            let batchVersion = entry.batch
            const previous = new Map(entry.tasks.map(task => [task.task_id, task]))
            const tasks = await client.tasks(id, signal)
            if (generation !== listGeneration || signal.aborted || disposed) return null
            applyTasks(id, tasks)
            let metadataAdvanced = false
            if (!listedBatchIds.has(id) || previous.size !== tasks.length || tasks.some(task => {
              const before = previous.get(task.task_id)
              return !before || before.status !== task.status || before.run_id !== task.run_id || before.result_revision !== task.result_revision
            })) {
              // A task may finish after the batch-list snapshot. Older pages
              // also need current package revisions, pairing and name sources.
              taskRefreshNeeded.add(id)
              const fresh = await client.batch(id, signal)
              if (generation !== listGeneration || signal.aborted || disposed) return null
              if (entry.batch === batchVersion) {
                metadataAdvanced = batchVersion?.status !== fresh.status || batchVersion?.updated_at !== fresh.updated_at ||
                  batchVersion?.package_revision !== fresh.package_revision
                upsertBatch(fresh)
                batchVersion = entry.batch
              }
            }
            if (!metadataAdvanced && entry.batch === batchVersion) taskRefreshNeeded.delete(id)
          } catch (error) {
            if (generation !== listGeneration || signal.aborted || disposed) return null
            if (!(error instanceof ApiFailure) || error.card.http_status !== 404) throw error
            const taskIds = entry.tasks.map(task => task.task_id)
            removeBatch(id, taskIds)
            options.onBatchRemoved?.(id, taskIds)
            removed = true
          }
        }
      }
      failures = 0
      state.failureCount = 0
      state.retrying = false
      state.lastCheckedAt = new Date().toISOString()
      return someRunning(state) || removed || taskRefreshNeeded.size > 0 ? intervalMs : null
    } catch (error) {
      if (isAbort(error) || generation !== listGeneration || disposed) return null
      if (error instanceof ApiFailure && error.card.http_status === 401) { reportUnauthorized(); return null }
      failures += 1
      state.failureCount = failures
      state.retrying = canRetryRead(error)
      return canRetryRead(error) ? retryDelay(failures) : null
    }
  }

  const loop = new ReadLoop(async signal => {
    const refreshTasks = refreshRequested
    refreshRequested = false
    const delay = await pollOnce(signal, refreshTasks)
    if (!signal.aborted && !disposed) state.polling = delay !== null
    return delay
  })

  function start() {
    if (disposed) return
    state.polling = true
    refreshRequested = true
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

  async function changePage(page: number, signal: AbortSignal, size = state.pageSize): Promise<void> {
    const client = getApi()
    if (!client || disposed) return
    if (!Number.isSafeInteger(page) || page < 1 || !Number.isSafeInteger(size) || size < 1 || size > 100) throw new Error('INVALID_PAGE')
    stop()
    const generation = ++listGeneration
    const previous = new Map(state.order.map(id => [id, state.entries[id]?.batch]))
    let failed = false
    try {
      let list = await client.batches(page, size, signal, state.dateRange)
      if (generation !== listGeneration || signal.aborted || disposed) return
      const last = Math.max(1, Math.ceil(list.total / size))
      if (page > last) list = await client.batches(last, size, signal, state.dateRange)
      if (generation !== listGeneration || signal.aborted || disposed) return
      state.page = list.page; state.pageSize = size; state.serverTotal = list.total
      state.listedIds = list.items.map(batch => batch.batch_id)
      for (const batch of list.items) {
        // Preserve metadata updated by a concurrent result/action while this page was read.
        if (state.entries[batch.batch_id]?.batch === previous.get(batch.batch_id)) upsertBatch(batch)
        taskRefreshNeeded.add(batch.batch_id)
      }
      sortBatches()
    } catch (error) {
      if (generation !== listGeneration || signal.aborted || disposed) return
      failed = true
      if (generation === listGeneration && error instanceof ApiFailure && error.card.http_status === 401) reportUnauthorized()
      throw error
    } finally {
      if (generation === listGeneration && !disposed && !unauthorizedNotified) {
        // Reconcile hidden running jobs even when a requested page failed or was cancelled.
        // Successful jumps already fetched the list; schedule the next poll instead of refetching immediately.
        state.polling = true
        loop.start(failed ? 0 : intervalMs)
      }
    }
  }

  function setDateRange(range: BatchDateRange | null) {
    if (JSON.stringify(range) === JSON.stringify(state.dateRange)) return
    stop()
    listGeneration += 1
    state.dateRange = range
    state.listedIds = []
    state.serverTotal = 0
    state.page = 1
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

  async function submitUpload(files: readonly File[], docType: UploadDocType, abnormalOnly: boolean, signal: AbortSignal,
    options: { personName?: string; targetBatch?: Batch; fileTypes?: readonly UploadDocType[] } = {}): Promise<{ batch_id: string; task_ids: string[] }> {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const created = options.targetBatch
      ? await client.append(options.targetBatch, files, docType, abnormalOnly, signal, options.fileTypes)
      : await client.upload(files, docType, abnormalOnly, signal, options.personName, options.fileTypes)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return created
    if (!state.entries[created.batch_id]) {
      state.entries[created.batch_id] = { batch: null, tasks: [], tasksLoaded: false, expanded: true }
      state.order.unshift(created.batch_id)
    }
    taskRefreshNeeded.add(created.batch_id)
    setDateRange(null)
    stop()
    listGeneration++ // An accepted upload supersedes any pending historical-page request.
    state.page = 1
    state.listedIds = [created.batch_id]
    setExpanded(created.batch_id, true)
    start()
    return created
  }

  async function confirmPerson(batch: Batch, name: string, signal: AbortSignal) {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const updated = await client.confirmPerson(batch, name, signal)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return updated
    stop()
    listGeneration++
    upsertBatch(updated)
    start()
    return updated
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
    removeBatch(batchId, result.task_ids)
    if (wasListed) state.serverTotal = Math.max(0, state.serverTotal - 1)
    state.page = Math.min(state.page, Math.max(1, Math.ceil(state.serverTotal / state.pageSize)))
    start()
    return result
  }

  async function deleteTask(batchId: string, task: Task, signal: AbortSignal) {
    const client = getApi()
    if (!client) throw new Error('NOT_CONNECTED')
    const generation = sessionGeneration
    const result = await client.deleteTask(batchId, task, signal)
    if (disposed || signal.aborted || generation !== sessionGeneration || getApi() !== client) return result
    stop()
    listGeneration++
    delete state.pending[task.task_id]
    if (result.batch_deleted) {
      const wasListed = state.listedIds.includes(batchId)
      removeBatch(batchId, [task.task_id])
      if (wasListed) state.serverTotal = Math.max(0, state.serverTotal - 1)
      state.page = Math.min(state.page, Math.max(1, Math.ceil(state.serverTotal / state.pageSize)))
    } else {
      const entry = state.entries[batchId]
      if (entry) entry.tasks = entry.tasks.filter(item => item.task_id !== task.task_id)
      taskRefreshNeeded.add(batchId)
    }
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
    state.page = 1
    state.pageSize = initialPageSize
    taskRefreshNeeded.clear()
    unauthorizedNotified = false
  }

  function dispose() { disposed = true; clear() }

  return { state, pollOnce, start, stop, onVisible, changePage, loadTasks, setDateRange, setExpanded, submitUpload, confirmPerson, runAction, deleteBatch, deleteTask, pendingNotice, entryOf, clear, dispose }
}
export type Monitor = ReturnType<typeof createMonitor>
