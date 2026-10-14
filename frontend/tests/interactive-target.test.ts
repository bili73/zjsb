// isInteractiveClickTarget：交互控件/图片上的点击不算“点空白”。Node 无 DOM，用最小 Element 桩验证分支与选择器。
import test from 'node:test'
import assert from 'node:assert/strict'
import { INTERACTIVE_CLICK_SELECTOR, isInteractiveClickTarget } from '../src/interactiveTarget.ts'

class FakeElement {
  static lastSelector = ''
  readonly hit: boolean
  constructor(hit: boolean) {
    this.hit = hit
  }
  closest(selector: string) {
    FakeElement.lastSelector = selector
    return this.hit ? ({}) : null
  }
}
;(globalThis as Record<string, unknown>).Element = FakeElement

test('clicks on interactive controls or images are not blank', () => {
  assert.equal(isInteractiveClickTarget(new FakeElement(true) as unknown as EventTarget), true)
  assert.equal(FakeElement.lastSelector, INTERACTIVE_CLICK_SELECTOR)
})

test('plain blank areas are blank', () => {
  assert.equal(isInteractiveClickTarget(new FakeElement(false) as unknown as EventTarget), false)
})

test('non-element targets and null are treated as blank', () => {
  assert.equal(isInteractiveClickTarget({} as unknown as EventTarget), false)
  assert.equal(isInteractiveClickTarget(null), false)
})

test('selector covers the critical interactive and image surfaces', () => {
  for (const part of ['button', 'input', 'textarea', 'label', 'summary', '.img-wrap', '.el-image', '.el-input-number', '.el-checkbox', '[role="button"]']) {
    assert.ok(INTERACTIVE_CLICK_SELECTOR.includes(part), `selector should include ${part}`)
  }
})
