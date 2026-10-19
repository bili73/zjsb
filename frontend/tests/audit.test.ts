import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiFailure, BusinessApi } from '../src/api.ts'
import { errorMessages } from '../src/diagnostics.ts'
import { auditActor, auditFailure, auditQuery, parseAuditDetail, parseAuditOptions, parseAuditPage, parseNumberedAuditPage } from '../src/audit.ts'
import { guideSteps } from '../src/guide.ts'

const row = { id: 'event-id', actor: 'old-user-id', identity: {}, event: 'export_full', description: '请求导出材料', outcome: 'legacy',
  outcome_label: '历史记录，结果未确认', created_at: '2026-10-16T00:00:00+00:00', task_id: null, run_id: null,
  batch_id: null, target_type: null, target_id: null, request_id: null, details: {}, legacy: true }

test('audit errors retain their specific safe recovery guidance without arbitrary server text', async () => {
  for (const code of ['AUDIT_FILTER_INVALID', 'AUDIT_EXPORT_TOO_LARGE']) {
    const api = new BusinessApi(async () => Response.json({ error: { code, message: 'PRIVATE_RAW_SERVER_TEXT' } }, { status: 422 }))
    await assert.rejects(api.auditExport({}, new AbortController().signal), error => {
      assert.ok(error instanceof ApiFailure)
      assert.equal(error.card.code, code)
      assert.doesNotMatch(JSON.stringify(error.card), /PRIVATE_RAW_SERVER_TEXT/)
      assert.match(errorMessages[error.card.code], /日期范围.*筛选条件/)
      if (code === 'AUDIT_EXPORT_TOO_LARGE') assert.match(errorMessages[error.card.code], /10000/)
      return true
    })
  }
})

test('legacy audit remains unknown; actors are never invented', () => {
  const result = parseAuditPage({ items: [row], next_cursor: null })
  assert.equal(result.items[0]!.outcome, 'legacy')
  assert.match(auditActor(result.items[0]!), /姓名未记录/)
  assert.throws(() => parseAuditPage({ items: [{ ...row, outcome: 'downloaded' }], next_cursor: null }))
  assert.throws(() => parseAuditPage({ items: [{ ...row, identity: { username: 42 } }], next_cursor: null }))
  assert.throws(() => parseAuditDetail({ ...row, changes: [], context: {}, history_state: 'missing' }))
  assert.equal(parseAuditDetail({ ...row, changes: [], context: {}, history_state: 'unavailable' }).history_state, 'unavailable')
})
test('audit options require valid identities and filters encode only allowed fields', () => {
  assert.throws(() => parseAuditOptions({ actors: [{}], events: [], outcomes: [] }))
  const query = new URLSearchParams(auditQuery({ actor: 'a&outcome=success', outcome: 'failure' }, 'opaque+cursor'))
  assert.equal(query.get('actor'), 'a&outcome=success'); assert.equal(query.get('outcome'), 'failure')
  assert.equal(query.get('cursor'), 'opaque+cursor')
})

test('audit summaries accept readable targets but reject malformed target content', () => {
  const summary = { ...row, description: '上传材料（10份材料）', object_label: '毕业证 · 2026-10-16 08:00' }
  assert.equal(parseAuditPage({ items: [summary], next_cursor: null }).items[0]!.object_label, summary.object_label)
  assert.throws(() => parseAuditPage({ items: [{ ...summary, object_label: { private: 'value' } }], next_cursor: null }))
  assert.equal(parseAuditPage({ items: [row], next_cursor: null }).items[0]!.object_label, undefined)
})
test('audit API uses protected endpoints, cancel signal and binary export', async () => {
  const calls: { url: string; init: RequestInit }[] = []
  const api = new BusinessApi(async (input, init) => {
    calls.push({ url: String(input), init: init! })
    return String(input).includes('/export') ? new Response(new Blob(['xlsx'])) : Response.json({ items: [row], next_cursor: null })
  })
  const controller = new AbortController()
  assert.equal((await api.auditEvents({ outcome: 'failure' }, null, controller.signal)).items.length, 1)
  assert.match(calls[0]!.url, /^\/api\/v1\/admin\/audit\/events\?outcome=failure$/)
  assert.equal(calls[0]!.init.credentials, 'same-origin')
  assert.equal(await (await api.auditExport({}, controller.signal)).text(), 'xlsx')
})
test('an account change aborts late audit content even if transport completes', async () => {
  const pending = Promise.withResolvers<Response>()
  const api = new BusinessApi(() => pending.promise)
  const controller = new AbortController()
  const result = api.auditEvents({}, null, controller.signal)
  controller.abort()
  pending.resolve(Response.json({ items: [row], next_cursor: null }))
  await assert.rejects(result, { name: 'AbortError' })
})
test('audit guide is administrator only and has only passive instruction steps', () => {
  assert.equal(guideSteps('audit', true, false).length, 0)
  assert.deepEqual(guideSteps('audit', true, true).map(item => item.anchor), ['audit-filter', 'audit-list', 'audit-export'])
})
test('login audit explains validation failures without suggesting an expired login', () => {
  const record = parseAuditPage({ items: [{ ...row, event: 'login', outcome: 'failure', details: { code: 'UNAUTHORIZED' } }], next_cursor: null }).items[0]!
  assert.match(auditFailure(record), /账号或密码验证未通过/)
  assert.doesNotMatch(auditFailure({ ...record, details: { code: 'PRIVATE_RAW_ERROR' } }), /PRIVATE_RAW_ERROR/)
})

test('numbered audit pages validate totals and jump directly in one request', async () => {
  const body = { items: [row], next_cursor: null, total: 402, page: 9, page_size: 50 }
  assert.equal(parseNumberedAuditPage(body).total, 402)
  for (const invalid of [{ total: -1 }, { total: '402' }, { page: 0 }, { page_size: 101 }, { total: undefined }]) {
    assert.throws(() => parseNumberedAuditPage({ ...body, ...invalid }))
  }
  const calls: string[] = []
  const api = new BusinessApi(async input => { calls.push(String(input)); return Response.json(body) })
  const result = await api.auditPage({ event: 'upload' }, 9, 50, new AbortController().signal)
  assert.equal(result.page, 9)
  assert.deepEqual(calls, ['/api/v1/admin/audit/events?event=upload&page=9&page_size=50'])
})
