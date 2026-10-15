import test from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer } from 'vue'
import * as d from '../src/diagnostics.ts'

test('browser diagnostics retain coordinates without an Error and classify without storing messages', () => {
  const listeners = new Map<string, (event: unknown) => void>()
  const original = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    addEventListener: (name: string, fn: (event: unknown) => void) => listeners.set(name, fn),
    removeEventListener: (name: string) => listeners.delete(name),
  } })
  d.clearDiagnosticCards()
  const cleanup = d.installGlobalDiagnostics()
  try {
    listeners.get('error')!({ error: null, message: 'PRIVATE_MATERIAL', filename: 'https://private.invalid/secret', lineno: 321, colno: 45 })
    assert.deepEqual(d.diagnosticCards.value[0]?.stack_frames, [{ module: 'frontend', line: 321, column: 45 }])
    assert.equal(d.diagnosticCards.value[0]?.browser_event, 'javascript_error')
    for (const message of ['ResizeObserver loop limit exceeded', 'ResizeObserver loop completed with undelivered notifications.']) {
      listeners.get('error')!({ error: null, message, lineno: 0, colno: 0 })
      assert.equal(d.diagnosticCards.value[0]?.browser_event, 'resize_observer')
      assert.deepEqual(d.diagnosticCards.value[0]?.stack_frames, [])
    }
    listeners.get('error')!({ error: null, message: 'Script error.', lineno: -1, colno: Infinity })
    assert.equal(d.diagnosticCards.value[0]?.browser_event, 'opaque_script')
    const error = new TypeError('PRIVATE_MATERIAL')
    error.stack = 'TypeError: PRIVATE_MATERIAL\n at https://private.invalid/secret.js:81:9'
    listeners.get('error')!({ error, message: 'PRIVATE_MATERIAL', lineno: 99, colno: 99 })
    assert.equal(d.diagnosticCards.value[0]?.exception_type, 'TypeError')
    assert.deepEqual(d.diagnosticCards.value[0]?.stack_frames, [{ module: 'frontend', line: 81, column: 9 }])
    listeners.get('unhandledrejection')!({ reason: error })
    assert.equal(d.diagnosticCards.value[0]?.browser_event, 'promise_rejection')
    assert.ok(!JSON.stringify(d.diagnosticCards.value).includes('PRIVATE'))
    assert.ok(!JSON.stringify(d.diagnosticCards.value).includes('private.invalid'))
  } finally {
    cleanup(); assert.equal(listeners.size, 0); d.clearDiagnosticCards()
    if (original) Object.defineProperty(globalThis, 'window', original)
    else Reflect.deleteProperty(globalThis, 'window')
  }
})

test('Vue render failures use the same safe reporter', () => {
  const renderer = createRenderer({
    patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
    createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null },
  })
  const sent: d.DiagnosticCard[] = []
  const app = renderer.createApp({ render() { throw new TypeError('PRIVATE_RENDER_VALUE') } })
  const previous = console.error; console.error = () => {}
  d.clearDiagnosticCards(); d.setDiagnosticReporter(card => sent.push(card))
  try {
    d.installVueDiagnostics(app); app.mount({})
    assert.equal(sent.length, 1)
    assert.equal(sent[0]?.origin, 'vue')
    assert.equal(sent[0]?.browser_event, 'vue_error')
    assert.equal(sent[0]?.exception_type, 'TypeError')
    assert.ok(!JSON.stringify(sent).includes('PRIVATE'))
  } finally { app.unmount(); console.error = previous; d.setDiagnosticReporter(null); d.clearDiagnosticCards() }
})

test('build identity contains only an emitted bundle hash', () => {
  assert.equal(d.frontendBuildId('http://127.0.0.1:8765/assets/index-Abc_1234.js?private=secret'), 'b_Abc_1234')
  assert.equal(d.frontendBuildId('file:///private/src/diagnostics.ts'), null)
  assert.equal(d.frontendBuildId('http://127.0.0.1/src/main.ts'), null)
  assert.equal(d.frontendBuildId('private material'), null)
})
