import { isRecord } from './business.ts'
import { errorMessages, safeCode } from './diagnostics.ts'

export type AuditOutcome = 'success' | 'failure' | 'requested' | 'legacy'
export interface AuditFilters { date_from?: string; date_to?: string; actor?: string; event?: string; outcome?: AuditOutcome; batch_id?: string }
export interface AuditRecord {
  id: string; actor: string; identity: { username?: string; display_name?: string; role?: string }
  event: string; description: string; object_label?: string; outcome: AuditOutcome; outcome_label: string; created_at: string
  task_id: string | null; run_id: string | null; batch_id: string | null; target_type: string | null
  target_id: string | null; request_id: string | null; details: Record<string, unknown>; legacy: boolean
}
export interface AuditDetail extends AuditRecord {
  context: { peer?: string; claimed_username?: string; target?: { username?: string; display_name?: string }; name_change?: { before: string; after: string } }
  changes: { field: string; before: unknown; after: unknown }[]
  history_state: 'available' | 'unavailable' | 'not_applicable'
}
export interface AuditOptions {
  actors: { id: string; username: string; display_name: string; role: string }[]
  events: { value: string; label: string }[]; outcomes: { value: AuditOutcome; label: string }[]
}
function parseRecord(value: unknown): AuditRecord {
  if (!isRecord(value) || !['id', 'actor', 'event', 'description', 'outcome_label', 'created_at'].every(key => typeof value[key] === 'string') ||
      !['success', 'failure', 'requested', 'legacy'].includes(String(value.outcome)) || !isRecord(value.identity) || !isRecord(value.details) || typeof value.legacy !== 'boolean' ||
      !['task_id', 'run_id', 'batch_id', 'target_type', 'target_id', 'request_id'].every(key => value[key] === null || typeof value[key] === 'string') ||
      !(value.object_label === undefined || typeof value.object_label === 'string') ||
      !Object.values(value.identity).every(item => typeof item === 'string')) throw new Error('INVALID_RESPONSE')
  return value as unknown as AuditRecord
}
export function parseAuditPage(value: unknown): { items: AuditRecord[]; next_cursor: string | null } {
  if (!isRecord(value) || !Array.isArray(value.items) || !(value.next_cursor === null || typeof value.next_cursor === 'string')) throw new Error('INVALID_RESPONSE')
  return { items: value.items.map(parseRecord), next_cursor: value.next_cursor }
}
export function parseNumberedAuditPage(value: unknown) {
  const result = parseAuditPage(value)
  if (!isRecord(value) || !Number.isSafeInteger(value.total) || Number(value.total) < 0 ||
      !Number.isSafeInteger(value.page) || Number(value.page) < 1 ||
      !Number.isSafeInteger(value.page_size) || Number(value.page_size) < 1 || Number(value.page_size) > 100 ||
      result.items.length > Number(value.page_size)) throw new Error('INVALID_RESPONSE')
  return { ...result, total: value.total as number, page: value.page as number, page_size: value.page_size as number }
}
export function parseAuditDetail(value: unknown): AuditDetail {
  parseRecord(value)
  if (!isRecord(value) || !isRecord(value.context) || !['available', 'unavailable', 'not_applicable'].includes(String(value.history_state)) ||
      !Array.isArray(value.changes) || !value.changes.every(item => isRecord(item) && typeof item.field === 'string' && 'before' in item && 'after' in item)) throw new Error('INVALID_RESPONSE')
  return value as unknown as AuditDetail
}
export function parseAuditOptions(value: unknown): AuditOptions {
  if (!isRecord(value) || !Array.isArray(value.actors) || !value.actors.every(row => isRecord(row) && ['id', 'username', 'display_name', 'role'].every(key => typeof row[key] === 'string')) ||
      ![value.events, value.outcomes].every(items => Array.isArray(items) && items.every(row => isRecord(row) && typeof row.value === 'string' && typeof row.label === 'string'))) throw new Error('INVALID_RESPONSE')
  return value as unknown as AuditOptions
}
export function auditQuery(filters: AuditFilters, cursor?: string | null) {
  const query = new URLSearchParams()
  for (const key of ['date_from', 'date_to', 'actor', 'event', 'outcome', 'batch_id'] as const) if (filters[key]) query.set(key, filters[key]!)
  if (cursor) query.set('cursor', cursor)
  return query.toString()
}
export function auditActor(row: AuditRecord) {
  return row.identity.display_name ? `${row.identity.display_name}（${row.identity.username ?? row.actor}）` :
    ({ worker: '系统任务', system: '系统维护', anonymous: '未登录／身份未验证' }[row.actor] ?? `历史账号（姓名未记录）：${row.actor}`)
}
export function auditFailure(row: AuditRecord) {
  return row.event === 'login' && row.details.code === 'UNAUTHORIZED' ? '账号或密码验证未通过，或账号已被禁用。' :
    errorMessages[safeCode(row.details.code)]
}
