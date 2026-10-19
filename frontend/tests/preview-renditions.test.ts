import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiFailure, BusinessApi } from '../src/api.ts'
import type { Task } from '../src/business.ts'

const task = { task_id: crypto.randomUUID(), run_id: crypto.randomUUID(), result_revision: 3 } as Task
const signal = () => new AbortController().signal
const png = (rendition?: string) => new Response(new Blob(['synthetic pixels'], { type: 'image/png' }), {
  headers: { 'X-Preview-Stage': 'corrected', 'X-Result-Revision': '3', ...(rendition === undefined ? {} : { 'X-Preview-Rendition': rendition }) },
})

test('display is explicit in GET and legacy POST; original preserves the old request shape', async () => {
  const calls: { input: string; init: RequestInit }[] = []
  const api = new BusinessApi(async (input, init) => { calls.push({ input: String(input), init: init! }); return png('original') })
  await api.preview(task, 1, signal())
  assert.equal(new URL(calls[0]!.input, 'http://local').searchParams.has('rendition'), false)
  await api.preview(task, 2, signal(), undefined, 'display')
  const params = new URL(calls[1]!.input, 'http://local').searchParams
  assert.equal(params.get('rendition'), 'display'); assert.equal(params.get('stage'), 'corrected')
  assert.equal(params.get('run_id'), task.run_id); assert.equal(params.get('result_revision'), '3')
  await api.preview(task, 2, signal(), '人工核对', 'display')
  assert.deepEqual(JSON.parse(String(calls[2]!.init.body)), { run_id: task.run_id, expected_revision: 3, page: 2, reason: '人工核对', rendition: 'display' })
  await api.preview(task, 2, signal(), '人工核对', 'original')
  assert.equal(Object.hasOwn(JSON.parse(String(calls[3]!.init.body)), 'rendition'), false)
})

test('old servers remain compatible but display pixels cannot masquerade as original evidence', async () => {
  for (const requested of ['original', 'display'] as const) {
    const old = new BusinessApi(async () => png())
    const response = await old.preview(task, 1, signal(), undefined, requested)
    assert.equal(response.rendition, 'original'); assert.equal(response.corrected, true)
  }
  const display = new BusinessApi(async () => png('display'))
  assert.equal((await display.preview(task, 1, signal(), undefined, 'display')).rendition, 'display')
  await assert.rejects(display.preview(task, 1, signal()), e => e instanceof ApiFailure && e.card.code === 'INVALID_RESPONSE')
  for (const invalid of ['', 'thumbnail', 'ORIGINAL']) {
    const api = new BusinessApi(async () => png(invalid))
    await assert.rejects(api.preview(task, 1, signal(), undefined, 'display'), e => e instanceof ApiFailure && e.card.code === 'INVALID_RESPONSE')
  }
})
