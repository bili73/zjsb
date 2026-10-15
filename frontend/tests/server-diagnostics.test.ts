import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { clearDiagnosticCards, diagnosticCards, makeDiagnostic, recordDiagnostic, setDiagnosticReporter } from '../src/diagnostics.ts'
import { createDiagnosticMonitor, logQuery, parseLogPage, parseLogStatus } from '../src/serverDiagnostics.ts'
import type { LogStatus } from '../src/serverDiagnostics.ts'

const status: LogStatus = { recording_ok: true, backup_ok: true, scan_ok: true,
  last_check_at: '2026-10-15T04:00:00Z', last_backup_at: '2026-10-15T00:00:00Z', raw_bytes: 100,
  archive_bytes: 50, raw_limit_bytes: 512000, archive_limit_bytes: 1024000, error_count_24h: 2,
  latest_error_at: '2026-10-15T03:00:00Z', latest_error_id: 'l_' + 'a'.repeat(32), raw_retention_days: 7, backup_retention_days: 30 }
const nextTurn = () => new Promise(resolve => setImmediate(resolve))

test('diagnostic responses reject malformed levels, counters and pages', () => {
  assert.equal(parseLogStatus(status).backup_retention_days, 30)
  assert.throws(() => parseLogStatus({ ...status, raw_bytes: -1 }))
  assert.throws(() => parseLogStatus({ ...status, recording_ok: 'true' }))
  assert.deepEqual(parseLogPage({ items: [], next_cursor: null }), { items: [], next_cursor: null, incomplete: false, skipped_files: 0, skipped_records: 0 })
  const partial = { items: [], next_cursor: null, incomplete: true, skipped_files: 1, skipped_records: 2 }
  assert.deepEqual(parseLogPage(partial), partial)
  for (const change of [{ incomplete: 'true' }, { skipped_files: -1 }, { skipped_records: 0.5 }]) {
    assert.throws(() => parseLogPage({ ...partial, ...change }))
  }
  const row = { record_id: 'l_' + 'b'.repeat(32), timestamp: '2026-10-15T04:00:00Z', level: 'ERROR', app_version: '1.26.0', component: 'api', event: 'request_failed', context: {} }
  assert.equal(parseLogPage({ items: [row], next_cursor: null }).items.length, 1)
  assert.throws(() => parseLogPage({ items: [{ ...row, level: 'PRIVATE' }], next_cursor: null }))
  assert.throws(() => parseLogPage({ items: [{ ...row, timestamp: 'invalid' }], next_cursor: null }))
})

test('filter query uses encoded allowlisted controls without changing dates', () => {
  const query = new URLSearchParams(logQuery({ level: 'ERROR', date_from: '2026-10-15', date_to: '2026-10-15' }, 'opaque+/='))
  assert.equal(query.get('cursor'), 'opaque+/=')
  assert.equal(query.get('date_from'), '2026-10-15')
  assert.equal(query.get('task_id'), null)
})

test('log descriptions preserve server Chinese text and provide a legacy fallback', () => {
  const row = { record_id: 'l_' + 'b'.repeat(32), timestamp: '2026-10-15T04:00:00Z', level: 'ERROR', app_version: '1.26.0', component: 'api', event: 'request_failed', context: { error_code: 'INTERNAL_ERROR' } }
  const description = '服务处理请求时发生错误，请联系维护人员。'
  const page = parseLogPage({ items: [{ ...row, description }], next_cursor: null })
  assert.equal(page.items[0]?.description, description)
  assert.equal(page.items[0]?.event, 'request_failed')
  assert.equal(page.items[0]?.context.error_code, 'INTERNAL_ERROR')
  const legacy = parseLogPage({ items: [row, { ...row, description: '  ' }], next_cursor: null })
  assert.ok(legacy.items.every(item => item.description === '历史记录暂无中文说明，请展开查看技术详情。'))
  assert.equal('description' in row, false)
  assert.throws(() => parseLogPage({ items: [{ ...row, description: 123 }], next_cursor: null }))
})

test('frontend reporting sends safe fields and CSRF; failures do not recursively create errors', async () => {
  clearDiagnosticCards()
  const calls: { url: string; init: RequestInit }[] = []
  const api = new BusinessApi((async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} })
    if (String(url).endsWith('/auth/me')) return new Response(JSON.stringify({ user_id: '11111111-2222-4333-8444-555555555555', display_name: '合成账号', role: 'admin', permissions: [], csrf_token: 'a'.repeat(64) }))
    throw new Error('PRIVATE_SERVER_MESSAGE')
  }) as typeof fetch)
  const signal = new AbortController().signal
  await api.auth(signal)
  const card = recordDiagnostic({ origin: 'vue', operation: 'interface', code: 'CLIENT_ERROR', error: new Error('PRIVATE_OCR_CONTENT') })
  const count = diagnosticCards.value.length
  await assert.rejects(api.reportDiagnostic(card, signal))
  assert.equal(diagnosticCards.value.length, count)
  const request = calls[1]!
  assert.equal(new Headers(request.init.headers).get('X-CSRF-Token'), 'a'.repeat(64))
  const body = JSON.parse(String(request.init.body))
  assert.deepEqual(Object.keys(body).sort(), ['browser_event', 'client_error_id', 'code', 'column', 'exception_type', 'frontend_build', 'line', 'operation', 'origin', 'request_id'])
  assert.equal(body.exception_type, 'Error')
  assert.ok(!String(request.init.body).includes('PRIVATE'))
  clearDiagnosticCards()
})

test('only browser/connectivity failures report, duplicates and HTTP business failures stay local', () => {
  clearDiagnosticCards()
  const sent: string[] = []
  setDiagnosticReporter(card => sent.push(card.error_id))
  try {
    const id = 'e_' + '1'.repeat(32)
    recordDiagnostic({ origin: 'vue', operation: 'interface', code: 'CLIENT_ERROR', error_id: id })
    recordDiagnostic({ origin: 'vue', operation: 'interface', code: 'CLIENT_ERROR', error_id: id })
    recordDiagnostic({ origin: 'http', operation: 'export', code: 'EXPORT_BLOCKED', status: 409 })
    recordDiagnostic({ origin: 'http', operation: 'result', code: 'NETWORK_ERROR' })
    assert.equal(sent.length, 2)
    clearDiagnosticCards(); assert.equal(diagnosticCards.value.length, 0)
  } finally { setDiagnosticReporter(null) }
})

test('monitor never reads global logs for non-admin; stale admin response cannot survive account change', async () => {
  let requests = 0, complete!: (value: LogStatus) => void
  const api = { diagnosticStatus: () => { requests++; return new Promise<LogStatus>(resolve => { complete = resolve }) } } as unknown as BusinessApi
  const monitor = createDiagnosticMonitor(() => assert.fail('unexpected logout'))
  try {
    monitor.start(api, false); await nextTurn(); assert.equal(requests, 0)
    monitor.start(api, true); assert.equal(requests, 1)
    monitor.stop(); complete(status); await nextTurn()
    assert.equal(monitor.state.status, null); assert.equal(monitor.state.unseen, false)
  } finally { monitor.stop() }
})

test('monitor tracks new errors, acknowledges seen IDs and revokes sessions on 401', async () => {
  let value = status, unauthorized = 0
  const api = { diagnosticStatus: async () => value } as unknown as BusinessApi
  const monitor = createDiagnosticMonitor(() => { unauthorized++; monitor.stop() })
  try {
    monitor.start(api, true); await nextTurn(); assert.equal(monitor.state.unseen, true)
    monitor.acknowledge(); await monitor.refresh(); assert.equal(monitor.state.unseen, false)
    value = { ...status, latest_error_id: 'l_' + 'c'.repeat(32) }
    await monitor.refresh(); assert.equal(monitor.state.unseen, true)
    const denied = { diagnosticStatus: async () => { throw { card: makeDiagnostic({ origin: 'http', operation: 'diagnostics', status: 401, code: 'UNAUTHORIZED' }) } } } as unknown as BusinessApi
    monitor.start(denied, true); await nextTurn()
    assert.equal(unauthorized, 1); assert.equal(monitor.state.status, null)
  } finally { monitor.stop() }
})

test('diagnostic ZIP honors truncation and incomplete flags without recursive errors', async () => {
  clearDiagnosticCards()
  const api = new BusinessApi((async url => {
    if (String(url).includes('/bundle')) return new Response('zip bytes', { headers: { 'Content-Type': 'application/zip', 'X-Diagnostics-Truncated': 'true', 'X-Diagnostics-Incomplete': 'true' } })
    return new Response(JSON.stringify({ code: 'DIAGNOSTICS_UNAVAILABLE' }), { status: 503 })
  }) as typeof fetch)
  const result = await api.diagnosticBundle({}, new AbortController().signal)
  assert.equal(result.truncated, true)
  assert.equal(result.incomplete, true)
  await assert.rejects(api.diagnosticStatus(new AbortController().signal))
  assert.equal(diagnosticCards.value.length, 0)
})
