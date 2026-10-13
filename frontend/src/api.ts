import { recordDiagnostic, safeCode } from './diagnostics.ts'
import type { DiagnosticCard, Operation } from './diagnostics.ts'
import { isRecord, parseBatches, parseCatalogue, parseCreated, parseResult, parseTask, parseTasks, parseUser, parseManagedUser, parseManagedUsers, parseClassification } from './business.ts'
import type { Batch, ItemsFilter, Task, UploadDocType, User } from './business.ts'
import type { ReviewBody } from './review.ts'
import type { BatchDateRange } from './batchCalendar.ts'
import { parseRequiredFieldSettings } from './requiredFields.ts'
import type { RequiredFieldSave } from './requiredFields.ts'
import { parseRegionText } from './regionOcr.ts'
import type { RegionBox } from './regionOcr.ts'

export class ApiFailure extends Error {
  readonly card: DiagnosticCard
  constructor(card: DiagnosticCard) { super(card.code); this.name = 'ApiFailure'; this.card = card }
}
export function isAbort(error: unknown): boolean { return error instanceof DOMException && error.name === 'AbortError' }
export const retryDelay = (failures: number) => Math.min(30000, 2000 * 2 ** Math.min(failures - 1, 4))
export const canRetryRead = (error: unknown) => error instanceof ApiFailure && (['NETWORK_ERROR', 'REQUEST_TIMEOUT'].includes(error.card.code) || (error.card.http_status ?? 0) >= 500)
export const shouldRefreshResult = (error: unknown) => error instanceof ApiFailure && error.card.http_status === 409 && ['INVALID_STATE', 'RESULT_VERSION_CONFLICT'].includes(error.card.code)
export function resultConflictAction(error: unknown, status: Task['status'], alreadyRefreshed: boolean): 'refresh' | 'unavailable' | null {
  if (!shouldRefreshResult(error)) return null
  return status !== 'FAILED' && !alreadyRefreshed ? 'refresh' : 'unavailable'
}

// Session credentials are HttpOnly cookies; only the CSRF token stays in memory.
export class BusinessApi {
  private csrfToken: string | undefined
  private readonly fetcher: typeof fetch
  constructor(fetcher: typeof fetch = fetch) { this.fetcher = fetcher }
  private async request<T>(path: string, operation: Operation, decoder: (body: unknown) => T, signal: AbortSignal, init: RequestInit = {}, binary = false): Promise<T> {
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) controller.abort()
    let timedOut = false
    const timeout = setTimeout(() => { timedOut = true; controller.abort() }, operation === 'upload' ? 180000 : operation === 'classify' ? 30000 : operation === 'export' || operation === 'preview' ? 60000 : 15000)
    let status: number | undefined
    let requestId: unknown
    try {
      const headers = new Headers(init.headers)
      if (this.csrfToken && init.method && !['GET', 'HEAD', 'OPTIONS'].includes(init.method)) headers.set('X-CSRF-Token', this.csrfToken)
      // Browser-native fetch requires the Window/global receiver, not this client.
      const response = await this.fetcher.call(globalThis, `/api/v1${path}`, { ...init, headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' })
      status = response.status
      requestId = response.headers.get('X-Request-ID')
      const body: unknown = response.ok && binary ? { blob: await response.blob(), stage: response.headers.get('X-Preview-Stage'), revision: response.headers.get('X-Result-Revision') } : await response.json().catch(() => null)
      signal.throwIfAborted()
      if (!response.ok) {
        const error = isRecord(body) && isRecord(body.error) ? body.error : isRecord(body) ? body : {}
        const fallback = status === 401 ? 'UNAUTHORIZED' : status === 403 ? 'FORBIDDEN' : status === 404 ? 'NOT_FOUND' : 'UNKNOWN_ERROR'
        const code = status === 401 ? fallback : safeCode(error.code) === 'UNKNOWN_ERROR' ? fallback : error.code
        throw new ApiFailure(recordDiagnostic({ origin: 'http', operation, code, status, request_id: requestId, error_id: error.error_id, stage: error.stage }))
      }
      try { return decoder(body) } catch { throw new ApiFailure(recordDiagnostic({ origin: 'http', operation, code: 'INVALID_RESPONSE', status, request_id: requestId })) }
    } catch (error) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (error instanceof ApiFailure) throw error
      throw new ApiFailure(recordDiagnostic({ origin: 'http', operation, code: timedOut ? 'REQUEST_TIMEOUT' : 'NETWORK_ERROR', status, request_id: requestId }))
    } finally { clearTimeout(timeout); signal.removeEventListener('abort', abort) }
  }
  async auth(signal: AbortSignal) {
    const user = await this.request('/auth/me', 'auth', parseUser, signal)
    this.csrfToken = user.csrf_token
    return user
  }
  async login(username: string, password: string, signal: AbortSignal) {
    const user = await this.request('/auth/login', 'auth', parseUser, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) })
    this.csrfToken = user.csrf_token
    return user
  }
  async logout(signal: AbortSignal) {
    await this.request('/auth/logout', 'auth', () => undefined, signal, { method: 'POST' })
    this.csrfToken = undefined
  }
  users(signal: AbortSignal) { return this.request('/admin/users', 'account_list', parseManagedUsers, signal) }
  createUser(body: { username: string; password: string; display_name: string; role: User['role'] }, signal: AbortSignal) {
    return this.request('/admin/users', 'account_create', parseManagedUser, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }
  catalogue(signal: AbortSignal) { return this.request('/doc-types', 'catalogue', parseCatalogue, signal) }
  updateUserEnabled(userId: string, enabled: boolean, signal: AbortSignal) {
    return this.request(`/admin/users/${encodeURIComponent(userId)}`, 'account_update', parseManagedUser, signal, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) })
  }
  deleteUser(userId: string, signal: AbortSignal) {
    return this.request(`/admin/users/${encodeURIComponent(userId)}`, 'account_delete', () => undefined, signal, { method: 'DELETE' })
  }
  updateUserName(userId: string, display_name: string, signal: AbortSignal) {
    return this.request(`/admin/users/${encodeURIComponent(userId)}`, 'account_update', parseManagedUser, signal, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name }) })
  }
  resetUserPassword(userId: string, newPassword: string, signal: AbortSignal) {
    return this.request(`/admin/users/${encodeURIComponent(userId)}/password`, 'password_change', () => undefined, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: newPassword }) })
  }
  async changePassword(currentPassword: string, newPassword: string, signal: AbortSignal) {
    await this.request('/auth/password', 'password_change', () => undefined, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) })
    this.csrfToken = undefined
  }
  requiredFields(signal: AbortSignal) { return this.request('/admin/required-fields', 'required_settings_read', parseRequiredFieldSettings, signal) }
  saveRequiredFields(body: RequiredFieldSave, signal: AbortSignal) {
    return this.request('/admin/required-fields', 'required_settings_save', parseRequiredFieldSettings, signal, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }
  review(taskId: string, body: ReviewBody, signal: AbortSignal) {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/review`, 'review', parseTask, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }
  preview(task: Pick<Task, 'task_id' | 'run_id' | 'result_revision'>, page: number, signal: AbortSignal, reason?: string) {
    const query = new URLSearchParams({ run_id: task.run_id, result_revision: String(task.result_revision), page: String(page), stage: 'corrected' })
    const init = reason === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: task.run_id, expected_revision: task.result_revision, page, reason }) }
    return this.request(`/tasks/${encodeURIComponent(task.task_id)}/preview${reason === undefined ? `?${query}` : ''}`, 'preview', body => {
      if (!isRecord(body) || !(body.blob instanceof Blob) || !body.blob.type.startsWith('image/')) throw new Error('INVALID_RESPONSE')
      return { blob: body.blob, corrected: body.stage === 'corrected' && body.revision === String(task.result_revision) }
    }, signal, init, true)
  }
  export(body: { batch_id?: string; task_ids?: string[]; masked: boolean; reason?: string; versions?: { task_id: string; run_id: string; result_revision: number }[] }, signal: AbortSignal) {
    return this.request('/export', 'export', value => {
      if (!isRecord(value) || !(value.blob instanceof Blob)) throw new Error('INVALID_RESPONSE')
      return value.blob
    }, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, format: 'xlsx' }) }, true)
  }
  batches(page: number, pageSize: number, signal: AbortSignal, range?: BatchDateRange | null) {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (range) { query.set('date_from', range.date_from); query.set('date_to', range.date_to) }
    return this.request(`/batches?${query}`, 'batch_list', parseBatches, signal)
  }
  tasks(batchId: string, signal: AbortSignal) { return this.request(`/batches/${encodeURIComponent(batchId)}/tasks`, 'batch_tasks', parseTasks, signal) }
  batch(batchId: string, signal: AbortSignal) {
    return this.request(`/batches/${encodeURIComponent(batchId)}`, 'batch_list', body => {
      const batch = parseBatches({ items: [body], total: 1, page: 1, page_size: 1 }).items[0]!
      if (batch.batch_id !== batchId) throw new Error('INVALID_RESPONSE')
      return batch
    }, signal)
  }
  deleteBatch(batchId: string, tasks: readonly Task[], signal: AbortSignal) {
    return this.request(`/batches/${encodeURIComponent(batchId)}`, 'batch_delete', body => {
      const created = parseCreated(body)
      if (!isRecord(body) || typeof body.cleanup_pending !== 'boolean' || created.batch_id !== batchId ||
        created.task_ids.length !== tasks.length || !created.task_ids.every(id => tasks.some(task => task.task_id === id))) throw new Error('INVALID_RESPONSE')
      return { ...created, cleanup_pending: body.cleanup_pending }
    }, signal, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      versions: tasks.map(task => ({ task_id: task.task_id, run_id: task.run_id, expected_revision: task.result_revision })),
    }) })
  }
  result(taskId: string, itemsFilter: ItemsFilter | undefined, signal: AbortSignal) {
    const query = itemsFilter ? `?items_filter=${itemsFilter}` : ''
    return this.request(`/tasks/${encodeURIComponent(taskId)}/result${query}`, 'result', parseResult, signal)
  }
  classify(file: File, signal: AbortSignal) {
    const form = new FormData()
    form.append('files', file)
    return this.request('/classify', 'classify', parseClassification, signal, { method: 'POST', body: form })
  }
  ocrRegion(task: Task, field: string | null, page: number, bbox: RegionBox, signal: AbortSignal) {
    return this.request(`/tasks/${encodeURIComponent(task.task_id)}/ocr-region`, 'region_ocr',
      body => parseRegionText(body, task, field, page, bbox), signal,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          run_id: task.run_id, expected_revision: task.result_revision, ...(field === null ? {} : { field_key: field }), page, bbox,
      }) })
  }
  upload(files: readonly File[], docType: UploadDocType, abnormalOnly: boolean, signal: AbortSignal, personName?: string, fileTypes?: readonly UploadDocType[]) {
    const form = new FormData()
    files.forEach(file => form.append('files', file))
    if (fileTypes) form.append('file_types', JSON.stringify(fileTypes))
    else form.append('doc_type_hint', docType)
    form.append('abnormal_only', String((fileTypes?.includes('MEDICAL_REPORT') ?? docType === 'MEDICAL_REPORT') && abnormalOnly))
    if (personName !== undefined) form.append('person_name', personName)
    return this.request('/batches', 'upload', parseCreated, signal, { method: 'POST', body: form })
  }
  confirmPerson(batch: Batch, personName: string, signal: AbortSignal) {
    return this.request(`/batches/${encodeURIComponent(batch.batch_id)}/person`, 'person_update', body => {
      const updated = parseBatches({ items: [body], total: 1, page: 1, page_size: 1 }).items[0]!
      if (updated.batch_id !== batch.batch_id) throw new Error('INVALID_RESPONSE')
      return updated
    }, signal, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_name: personName, expected_revision: batch.package_revision }) })
  }
  append(batch: Batch, files: readonly File[], docType: UploadDocType, abnormalOnly: boolean, signal: AbortSignal, fileTypes?: readonly UploadDocType[]) {
    const form = new FormData()
    files.forEach(file => form.append('files', file))
    if (fileTypes) form.append('file_types', JSON.stringify(fileTypes))
    else form.append('doc_type_hint', docType)
    form.append('abnormal_only', String((fileTypes?.includes('MEDICAL_REPORT') ?? docType === 'MEDICAL_REPORT') && abnormalOnly))
    form.append('expected_revision', String(batch.package_revision))
    return this.request(`/batches/${encodeURIComponent(batch.batch_id)}/append`, 'upload', body => {
      const created = parseCreated(body)
      if (created.batch_id !== batch.batch_id) throw new Error('INVALID_RESPONSE')
      return created
    }, signal, { method: 'POST', body: form })
  }
  mutate(task: Task, operation: 'cancel' | 'rerun', signal: AbortSignal) {
    return this.request(`/tasks/${encodeURIComponent(task.task_id)}/${operation}`, operation, parseTask, signal, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: task.run_id, expected_revision: task.result_revision }) })
  }
}
