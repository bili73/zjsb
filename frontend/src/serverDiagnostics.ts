import { reactive } from 'vue'
import type { BusinessApi } from './api.ts'

export const logLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
export type LogLevel = typeof logLevels[number]
export interface LogStatus {
  recording_ok: boolean; backup_ok: boolean | null; scan_ok: boolean | null
  last_check_at: string | null; last_backup_at: string | null
  raw_bytes: number; archive_bytes: number; raw_limit_bytes: number; archive_limit_bytes: number
  error_count_24h: number; latest_error_at: string | null; latest_error_id: string | null
  raw_retention_days: number; backup_retention_days: number
}
export interface LogRecord {
  record_id: string; timestamp: string; level: LogLevel; app_version: string
  component: string; event: string; description: string; context: Record<string, unknown>; exceptions?: unknown[]
}
export interface LogPage {
  items: LogRecord[]; next_cursor: string | null
  incomplete: boolean; skipped_files: number; skipped_records: number
}
export interface LogFilters { level?: LogLevel; date_from?: string; date_to?: string; error_id?: string; task_id?: string }
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const optionalText = (value: unknown) => value === null || typeof value === 'string'
export function parseLogStatus(value: unknown): LogStatus {
  if (!record(value) || typeof value.recording_ok !== 'boolean' ||
      !['backup_ok', 'scan_ok'].every(key => value[key] === null || typeof value[key] === 'boolean') ||
      !['last_check_at', 'last_backup_at', 'latest_error_at', 'latest_error_id'].every(key => optionalText(value[key])) ||
      !['raw_bytes', 'archive_bytes', 'raw_limit_bytes', 'archive_limit_bytes', 'error_count_24h', 'raw_retention_days', 'backup_retention_days'].every(key => Number.isSafeInteger(value[key]) && (value[key] as number) >= 0)) throw new Error('INVALID_RESPONSE')
  return value as unknown as LogStatus
}
export function parseLogPage(value: unknown): LogPage {
  if (!record(value) || !Array.isArray(value.items) || !optionalText(value.next_cursor) || !value.items.every(row =>
    record(row) && typeof row.record_id === 'string' && /^l_[a-f0-9]{32}$/.test(row.record_id) &&
    typeof row.timestamp === 'string' && Number.isFinite(Date.parse(row.timestamp)) &&
    logLevels.includes(row.level as LogLevel) && typeof row.app_version === 'string' &&
    typeof row.component === 'string' && typeof row.event === 'string' &&
    (row.description === undefined || typeof row.description === 'string') && record(row.context)) ||
    (value.incomplete !== undefined && typeof value.incomplete !== 'boolean') ||
    !['skipped_files', 'skipped_records'].every(key => value[key] === undefined || Number.isSafeInteger(value[key]) && (value[key] as number) >= 0)) throw new Error('INVALID_RESPONSE')
  const page = value as unknown as LogPage
  return { ...page, incomplete: page.incomplete ?? false, skipped_files: page.skipped_files ?? 0,
    skipped_records: page.skipped_records ?? 0, items: page.items.map(row => ({ ...row,
    description: row.description?.trim() || '历史记录暂无中文说明，请展开查看技术详情。' })) }
}
export function logQuery(filters: LogFilters, cursor?: string | null) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value)
  if (cursor) query.set('cursor', cursor)
  return query.toString()
}

export function createDiagnosticMonitor(onUnauthorized: () => void) {
  const state = reactive({ status: null as LogStatus | null, error: '', unseen: false })
  let client: BusinessApi | null = null
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let seen: string | null = null
  function stop() {
    generation++; client = null; controller?.abort(); controller = null; clearTimeout(timer)
    state.status = null; state.error = ''; state.unseen = false; seen = null
  }
  async function refresh() {
    clearTimeout(timer)
    if (!client || controller) return
    if (typeof document !== 'undefined' && document.hidden) { timer = setTimeout(refresh, 30000); return }
    const current = client, revision = generation
    const pending = new AbortController(); controller = pending
    try {
      const status = await current.diagnosticStatus(pending.signal)
      if (generation !== revision) return
      state.status = status; state.error = ''
      state.unseen = !!status.latest_error_id && status.latest_error_id !== seen
    } catch (error) {
      if (generation !== revision || pending.signal.aborted) return
      if (error && typeof error === 'object' && 'card' in error && record(error.card) && error.card.http_status === 401) { onUnauthorized(); return }
      state.status = null; state.error = '诊断状态暂时无法读取'
    } finally {
      if (generation === revision) { controller = null; if (client) timer = setTimeout(refresh, 30000) }
    }
  }
  function start(value: BusinessApi, admin: boolean) { stop(); if (admin) { client = value; void refresh() } }
  function acknowledge() { seen = state.status?.latest_error_id ?? null; state.unseen = false }
  return { state, start, stop, refresh, acknowledge }
}
