import test from 'node:test'
import assert from 'node:assert/strict'
import { needsStartupRefresh, parseHealth } from '../src/health.ts'

const healthy = {
  status: 'ok', version: '1.11.0', queue_depth: 0,
  components: { db: 'ok', worker: 'ok', storage: 'ok' },
}

const runtime = (overrides: Record<string, unknown> = {}) => ({
  configured_mode: 'dual_resident', effective_mode: 'dual_resident', state: 'ready',
  models: { glm_ocr: 'ready', paddleocr_vl: 'ready' }, reason_code: null, ...overrides,
})

test('parseHealth accepts a full snapshot', () => {
  const parsed = parseHealth({ ...healthy, runtime: runtime() })
  assert.equal(parsed.runtime?.state, 'ready')
  assert.deepEqual(parsed.components, { db: 'ok', worker: 'ok', storage: 'ok' })
})

test('parseHealth rejects malformed payloads without inventing state', () => {
  assert.throws(() => parseHealth(null), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, status: 'unknown' }), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, queue_depth: -1 }), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, components: { db: 'ok', worker: 'ok' } }), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, runtime: runtime({ state: 'crashed' }) }), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, runtime: runtime({ effective_mode: 'turbo' }) }), /INVALID_HEALTH/)
  assert.throws(() => parseHealth({ ...healthy, runtime: runtime({ models: { glm_ocr: 'ready' } }) }), /INVALID_HEALTH/)
})

test('parseHealth tolerates a missing runtime block', () => {
  const parsed = parseHealth(healthy)
  assert.equal(parsed.runtime, undefined)
})

test('needsStartupRefresh tracks transient model states only', () => {
  assert.equal(needsStartupRefresh({ ...healthy, runtime: runtime({ state: 'starting' }) }), true)
  assert.equal(needsStartupRefresh({ ...healthy, runtime: runtime({ state: 'stopping' }) }), true)
  assert.equal(needsStartupRefresh({ ...healthy, runtime: runtime({ models: { glm_ocr: 'warming', paddleocr_vl: 'ready' } }) }), true)
  assert.equal(needsStartupRefresh({ ...healthy, runtime: runtime({ state: 'degraded' }) }), false)
  assert.equal(needsStartupRefresh({ ...healthy, runtime: runtime({ models: { glm_ocr: 'failed', paddleocr_vl: 'ready' } }) }), false)
  assert.equal(needsStartupRefresh(healthy), false)
})
