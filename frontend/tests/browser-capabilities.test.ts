import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { copyText, randomId, sha256Hex } from '../src/browserCapabilities.ts'
import { makeDiagnostic } from '../src/diagnostics.ts'
import { LocalPreviewBatch } from '../src/workbench.ts'
import type { Task } from '../src/business.ts'

function replace(name: string, value: unknown) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, name)
  Object.defineProperty(globalThis, name, { configurable: true, value })
  return () => { if (previous) Object.defineProperty(globalThis, name, previous); else Reflect.deleteProperty(globalThis, name) }
}

test('HTTP UUIDs are v4, keep server identity and never include exception contents', () => {
  const real = crypto
  const restore = replace('crypto', { getRandomValues: real.getRandomValues.bind(real) })
  try {
    const ids = Array.from({ length: 100 }, randomId)
    assert.equal(new Set(ids).size, 100)
    assert.ok(ids.every(id => /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(id)))
    const card = makeDiagnostic({ origin: 'window', operation: 'interface', error: new TypeError('PRIVATE_DOCUMENT') })
    assert.ok(ids.every(id => id !== card.error_id))
    assert.ok(!JSON.stringify(card).includes('PRIVATE_DOCUMENT'))
    assert.equal(makeDiagnostic({ origin: 'http', operation: 'health', error_id: ids[0] }).error_id, ids[0])
  } finally { restore() }
})

test('HTTP SHA-256 matches standard vectors and the maximum single upload', async () => {
  const native = crypto
  const restore = replace('crypto', { getRandomValues: native.getRandomValues.bind(native) })
  try {
    for (const data of [new Uint8Array(), new TextEncoder().encode('abc'), new TextEncoder().encode('00123\n中文'), new Uint8Array(50 * 1024 * 1024).fill(97)]) {
      assert.equal(await sha256Hex(data.buffer), createHash('sha256').update(data).digest('hex'))
    }
  } finally { restore() }
  assert.equal(await sha256Hex(new TextEncoder().encode('abc').buffer), createHash('sha256').update('abc').digest('hex'))
})

test('HTTP preview binding preserves duplicate-name matching and logout invalidation', async () => {
  const native = crypto
  const restore = replace('crypto', { getRandomValues: native.getRandomValues.bind(native) })
  const a = new File(['abc'], 'crop.png'), b = new File(['def'], 'crop.png')
  const ids = ['11111111-2222-4333-8444-555555555555', '66666666-7777-4888-9999-000000000000']
  const tasks = [b, a].map((file, i) => ({ task_id: ids[1 - i], content_hash: createHash('sha256').update(i ? 'abc' : 'def').digest('hex') })) as Task[]
  const cache = new LocalPreviewBatch(5, file => file === a ? 'blob:a' : 'blob:b', () => {})
  try {
    assert.equal(await cache.addMatched([a, a, b], tasks), true)
    assert.equal(cache.get(ids[0]!)?.url, 'blob:a'); assert.equal(cache.get(ids[1]!)?.url, 'blob:b')
    const pending = cache.addMatched([a], tasks); cache.clear()
    assert.equal(await pending, false); assert.equal(cache.get(ids[0]!), undefined)
  } finally { cache.clear(); restore() }
})

test('copy uses synchronous HTTP selection, restores focus and rejects false/throw results', async () => {
  const nav = replace('navigator', {})
  let selected = false, removed = 0, restored = 0, appended = 0, copied = ''
  let outcome: boolean | Error = true
  const field = { value: '', readOnly: false, style: { cssText: '' }, focus() {}, select() { selected = true }, remove() { removed++ } }
  const parent = { appendChild(value: unknown) { assert.equal(value, field); appended++ } }
  const dom = replace('document', { activeElement: { isConnected: true, closest: () => parent, focus() { restored++ } },
    body: { appendChild() { assert.fail('must stay in the active dialog') } }, createElement: () => field,
    execCommand(command: string) { assert.equal(command, 'copy'); assert.equal(selected, true); copied = field.value; if (outcome instanceof Error) throw outcome; return outcome } })
  try {
    const pending = copyText('00123\n中文')
    assert.equal(copied, '00123\n中文', 'HTTP fallback must execute in the initiating click stack')
    await pending
    for (outcome of [false, new Error('denied')]) await assert.rejects(copyText('2024-06'))
    assert.equal(removed, 3); assert.equal(restored, 3); assert.equal(appended, 3)
  } finally { dom(); nav() }
})

test('modern clipboard rejection cannot trigger a stale legacy write', async () => {
  const pending = Promise.withResolvers<void>(); let active = true, fallback = 0
  const nav = replace('navigator', { clipboard: { writeText: () => pending.promise } })
  const dom = replace('document', { createElement() { fallback++; throw new Error('unexpected') } })
  try {
    const copying = copyText('old text', () => active)
    active = false; pending.reject(new Error('denied'))
    await assert.rejects(copying); assert.equal(fallback, 0)
    await assert.rejects(copyText('already stale', () => false)); assert.equal(fallback, 0)
  } finally { dom(); nav() }
})
