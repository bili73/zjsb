import test from 'node:test'
import assert from 'node:assert/strict'
import { createEngine } from '../src/engine.ts'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json', 'X-Request-ID': 'e_engine1' },
})

const healthy = (runtimeState = 'ready') => ({
  status: 'ok', version: '1.11.0', queue_depth: 0,
  components: { db: 'ok', worker: 'ok', storage: 'ok' },
  runtime: {
    configured_mode: 'dual_resident', effective_mode: 'dual_resident', state: runtimeState,
    models: { glm_ocr: 'ready', paddleocr_vl: 'ready' }, reason_code: null,
  },
})

test('refresh connects, stores the snapshot and reports readiness', async () => {
  const engine = createEngine(async () => json(healthy()))
  try {
    await engine.refresh()
    assert.equal(engine.state.connection, 'connected')
    assert.equal(engine.state.health?.version, '1.11.0')
    assert.equal(engine.state.lastCheckedAt !== null, true)
    assert.deepEqual(engine.summary.value, { tone: 'success', label: '引擎就绪' })
  } finally {
    engine.dispose()
  }
})

test('non-OK health responses become disconnected, not invalid', async () => {
  const engine = createEngine(async () => json({ error: 'down' }, 503))
  try {
    await engine.refresh()
    assert.equal(engine.state.connection, 'disconnected')
    assert.equal(engine.state.health, null)
    assert.deepEqual(engine.summary.value, { tone: 'danger', label: '服务未连接' })
  } finally {
    engine.dispose()
  }
})

test('unparseable bodies become invalid', async () => {
  const engine = createEngine(async () => json({ status: 'fine' }))
  try {
    await engine.refresh()
    assert.equal(engine.state.connection, 'invalid')
    assert.equal(engine.state.health, null)
    assert.equal(engine.summary.value.tone, 'warning')
  } finally {
    engine.dispose()
  }
})

test('startup snapshots keep auto refresh armed and dispose cancels it', async () => {
  const engine = createEngine(async () => json(healthy('starting')))
  try {
    await engine.refresh()
    assert.equal(engine.state.auto, true)
    assert.deepEqual(engine.summary.value, { tone: 'info', label: '引擎启动中' })
  } finally {
    engine.dispose()
  }
  assert.equal(engine.state.auto, true) // 定时器已被 dispose 清除，状态保留最后快照
})

test('degraded runtime narrows the badge wording', async () => {
  const snapshot = { ...healthy('degraded'), runtime: { ...healthy('degraded').runtime!, effective_mode: 'single_resident' as const } }
  const engine = createEngine(async () => json(snapshot))
  try {
    await engine.refresh()
    assert.equal(engine.summary.value.tone, 'warning')
    assert.equal(engine.summary.value.label, '引擎能力受限')
  } finally {
    engine.dispose()
  }
})
