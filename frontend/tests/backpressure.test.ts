import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiFailure, BusinessApi } from '../src/api.ts'
import { errorMessages } from '../src/diagnostics.ts'

const id = '11111111-2222-4333-8444-555555555555'
test('busy review responses retain exact draft payload and are never automatically replayed', async () => {
  for (const [status, code] of [[503, 'SERVICE_BUSY'], [429, 'OPERATION_THROTTLED']] as const) {
    const draft = { run_id: id, expected_revision: 4, fields: { name: '合成待保存内容' } }
    const before = structuredClone(draft)
    let calls = 0
    const api = new BusinessApi((async (_url, options) => {
      calls++
      assert.deepEqual(JSON.parse(String(options?.body)), before)
      return new Response(JSON.stringify({ code, message: 'private server text must not be reflected' }),
        { status, headers: { 'Retry-After': '2' } })
    }) as typeof fetch)
    await assert.rejects(api.review(id, draft, new AbortController().signal), error => {
      assert.ok(error instanceof ApiFailure)
      assert.equal(error.card.code, code)
      assert.equal(error.retryAfterSeconds, 2)
      assert.ok(!JSON.stringify(error.card).includes('private server'))
      assert.match(errorMessages[error.card.code], /繁忙|正在处理/)
      return true
    })
    assert.equal(calls, 1)
    assert.deepEqual(draft, before)
  }
})

test('busy export does not manufacture a download or change selected versions', async () => {
  let calls = 0
  const selection = { task_ids: [id], versions: [{ task_id: id, run_id: id, result_revision: 4 }], masked: false }
  const before = structuredClone(selection)
  const api = new BusinessApi((async () => {
    calls++
    return new Response(JSON.stringify({ code: 'SERVICE_BUSY' }), { status: 503, headers: { 'Retry-After': 'invalid' } })
  }) as typeof fetch)
  await assert.rejects(api.export(selection, new AbortController().signal), error =>
    error instanceof ApiFailure && error.card.code === 'SERVICE_BUSY' && error.retryAfterSeconds === undefined)
  assert.equal(calls, 1)
  assert.deepEqual(selection, before)
})
