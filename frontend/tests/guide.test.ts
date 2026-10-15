import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, readdir, access } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { detailGuideContext, findGuideTarget, guideSteps } from '../src/guide.ts'
import type { GuideContext } from '../src/guide.ts'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath = fileURLToPath(new URL('../src/components/OperationGuide.vue', import.meta.url))
const source = (await readFile(sourcePath, 'utf8')).replace('</script>',
  'defineExpose({start, close, open, current, steps, target, locating})\n</script>')
const compiled = compileScript(parse(source, { filename: sourcePath }).descriptor, { id: 'guide-test' })
const dataUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const code = ts.transpileModule(compiled.content, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
  if (specifier === 'element-plus') return `from '${dataUrl('export const ElTour = {}; export const ElTourStep = {};')}'`
  const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(sourcePath), specifier)
    : specifier === '@element-plus/icons-vue' ? require.resolve('@element-plus/icons-vue/dist/index.js') : require.resolve(specifier)
  return `from '${pathToFileURL(resolved).href}'`
})
const Component = (await import(dataUrl(code))).default
Component.render = () => null
const renderer = vue.createRenderer({
  patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
  createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null },
})
class Element {
  isConnected = true; visible = true; visibility = 'visible'; y = 100; scrolls = 0; focused = 0
  classes = new Set<string>()
  classList = { add: (name: string) => this.classes.add(name), remove: (name: string) => this.classes.delete(name) }
  children = new Map<string, Element[]>()
  getClientRects() { return this.visible ? [this.getBoundingClientRect()] : [] }
  getBoundingClientRect() { return { x: 20, y: this.y, width: 100, height: 40 } }
  scrollIntoView() { this.scrolls++ }
  focus() { this.focused++ }
  querySelectorAll(selector: string) { return this.children.get(selector) ?? [] }
}
function harness(context: GuideContext = 'review', canWrite = true) {
  let now = 0, serial = 0
  const callbacks = new Map<number, FrameRequestCallback>()
  const listeners = new Map<string, EventListener>()
  const original = new Map<string, PropertyDescriptor | undefined>()
  const replace = (key: string, value: unknown) => {
    original.set(key, Object.getOwnPropertyDescriptor(globalThis, key))
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  }
  const document = new Element(), scope = new Element(), trigger = new Element()
  document.children.set('[data-guide-scope="own-batch"]', [scope])
  const targets = new Map(guideSteps(context, canWrite, true).map(s => [s.anchor, new Element()]))
  for (const [anchor, element] of targets) scope.children.set(`[data-guide="${anchor}"]`, [element])
  replace('document', document)
  replace('getComputedStyle', (element: Element) => ({ visibility: element.visibility }))
  replace('matchMedia', () => ({ matches: false }))
  replace('performance', { now: () => now })
  replace('requestAnimationFrame', (fn: FrameRequestCallback) => { callbacks.set(++serial, fn); return serial })
  replace('cancelAnimationFrame', (id: number) => callbacks.delete(id))
  replace('window', { addEventListener: (key: string, fn: EventListener) => listeners.set(key, fn), removeEventListener: (key: string) => listeners.delete(key) })
  const app = renderer.createApp(Component, { context, scope: 'own-batch', canWrite, isAdmin: false })
  app.mount({})
  const exposed = app._instance.exposed
  const advance = async (count = 3) => {
    for (let i = 0; i < count; i++) {
      now += 150
      const batch = [...callbacks.values()]; callbacks.clear(); batch.forEach(fn => fn(now))
      await vue.nextTick()
    }
  }
  return { app, exposed, document, scope, trigger, targets, listeners, callbacks, advance,
    start: () => exposed.start({ currentTarget: trigger }),
    dispose() {
      app.unmount()
      assert.equal(callbacks.size, 0); assert.equal(listeners.size, 0)
      for (const [key, descriptor] of original) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('guides follow document type, keep admin instructions private and omit write steps for viewers', () => {
  assert.equal(detailGuideContext('MEDICAL_REPORT'), 'medical')
  assert.equal(detailGuideContext('TABLE'), 'table')
  assert.equal(detailGuideContext('GENERIC'), 'generic')
  assert.equal(detailGuideContext('BANK_CARD'), 'review')
  for (const context of ['accounts', 'required', 'retention'] as const) assert.deepEqual(guideSteps(context, true, false), [])
  for (const context of ['review', 'medical', 'generic', 'table', 'batch', 'package'] as const) {
    assert.ok(guideSteps(context, true, false).length <= 6)
    assert.ok(guideSteps(context, false, false).every(step => !step.write))
    assert.ok(!guideSteps(context, false, false).some(step => /-save|detail-export|-append/.test(step.anchor)))
  }
})

test('target lookup never borrows another batch, hidden pane or ambiguous element', () => {
  const h = harness()
  try {
    const lookup = () => findGuideTarget(h.document as unknown as ParentNode, 'own-batch', 'source-tools')
    assert.equal(lookup(), h.targets.get('source-tools'))
    h.scope.visible = false; assert.equal(lookup(), undefined); h.scope.visible = true
    h.targets.get('source-tools')!.visibility = 'hidden'; assert.equal(lookup(), undefined)
    h.scope.children.delete('[data-guide="source-tools"]')
    const other = new Element(); other.children.set('[data-guide="source-tools"]', [new Element()])
    h.document.children.set('[data-guide-scope="other-batch"]', [other]); assert.equal(lookup(), undefined)
    h.scope.children.set('[data-guide="source-tools"]', [new Element(), new Element()]); assert.equal(lookup(), undefined)
    assert.equal(findGuideTarget(h.document as unknown as ParentNode, 'bad"]', 'source-tools'), undefined)
  } finally { h.dispose() }
})

test('tour follows scrolled targets; changing steps removes the previous highlight', async () => {
  const h = harness()
  try {
    await h.start(); await h.advance()
    const first = h.targets.get('source-tools')!
    assert.equal(h.exposed.target.value(), first); assert.equal(first.scrolls, 1)
    const previous = h.exposed.target.value
    first.y = 180; await h.advance(1)
    assert.notEqual(h.exposed.target.value, previous)
    assert.equal(first.scrolls, 1)
    h.exposed.current.value++; await vue.nextTick(); await h.advance()
    assert.ok(!first.classes.has('operation-guide-target'))
    assert.equal(h.exposed.target.value(), h.targets.get('result-fields'))
  } finally { h.dispose() }
})

test('loading or absent anchors show fallback, then bind only when the target appears', async () => {
  const h = harness()
  try {
    h.scope.children.clear(); await h.start(); await h.advance(7)
    assert.equal(h.exposed.target.value, undefined); assert.equal(h.exposed.locating.value, false)
    const element = new Element(); h.scope.children.set('[data-guide="source-tools"]', [element]); await h.advance()
    assert.equal(h.exposed.target.value(), element)
    element.isConnected = false; await h.advance(1)
    assert.equal(h.exposed.target.value, undefined); assert.equal(element.classes.size, 0)
  } finally { h.dispose() }
})

test('Esc stops propagation, closes just the guide and removes listeners and highlight', async () => {
  const h = harness()
  try {
    await h.start(); await h.advance()
    let prevented = false, stopped = false
    h.listeners.get('keydown')!({ key: 'Escape', preventDefault: () => { prevented = true }, stopImmediatePropagation: () => { stopped = true } } as unknown as Event)
    assert.ok(prevented && stopped); assert.equal(h.exposed.open.value, false)
    assert.equal(h.targets.get('source-tools')!.classes.size, 0)
    assert.equal(h.callbacks.size, 0); assert.equal(h.listeners.size, 0); assert.equal(h.trigger.focused, 1)
  } finally { h.dispose() }
})

test('resolved guide anchors recover after hiding, removal and immediate replacement', async () => {
  const h = harness()
  try {
    await h.start(); await h.advance()
    let element = h.targets.get('source-tools')!
    for (const mode of ['hidden', 'removed', 'replaced']) {
      if (mode === 'hidden') element.visible = false
      else element.isConnected = false
      if (mode !== 'replaced') {
        await h.advance(7)
        assert.equal(h.exposed.target.value, undefined)
        assert.ok(!element.classes.has('operation-guide-target'))
        if (mode === 'hidden') element.visible = true
        else element.isConnected = true
      } else {
        const previous = element
        element = new Element()
        h.scope.children.set('[data-guide="source-tools"]', [element])
        await h.advance(1)
        assert.ok(!previous.classes.has('operation-guide-target'))
        assert.equal(h.exposed.target.value, undefined)
        assert.equal(h.exposed.locating.value, true)
      }
      await h.advance()
      assert.equal(h.exposed.target.value?.(), element, mode)
      assert.ok(element.classes.has('operation-guide-target'), mode)
      assert.equal(h.exposed.locating.value, false, mode)
    }
  } finally { h.dispose() }
})

test('close during nextTick, page change, permission loss and unmount cancel pending positioning', async () => {
  const h = harness()
  try {
    const opening = h.start(); h.exposed.close(); await opening
    assert.equal(h.callbacks.size, 0)
    for (const [key, value] of [['resetKey', 'another-task'], ['context', 'table'], ['canWrite', false], ['active', false]] as const) {
      await h.start(); await h.advance()
      h.app._instance.props[key] = value; await vue.nextTick()
      assert.equal(h.exposed.open.value, false, key); assert.equal(h.callbacks.size, 0)
    }
    h.app._instance.props.active = true; await vue.nextTick(); await h.start(); await h.advance()
  } finally { h.dispose() }
})

test('all guide anchors exist in the real Vue templates and manual chapter/image links resolve', async () => {
  const dir = new URL('../src/components/', import.meta.url)
  const templates = await Promise.all((await readdir(dir)).filter(name => name.endsWith('.vue')).map(name => readFile(new URL(name, dir), 'utf8')))
  const anchors = new Set(templates.join('\n').matchAll(/data-guide="([a-z-]+)"/g).map(match => match[1]))
  for (const context of ['upload','batches','batch','package','review','medical','table','generic','engine','accounts','required','retention'] as const) {
    for (const step of guideSteps(context, true, true)) assert.ok(anchors.has(step.anchor), `${context}: missing ${step.anchor}`)
  }
  const help = await readFile(new URL('../public/help/index.html', import.meta.url), 'utf8')
  const ids = new Set(help.matchAll(/\bid="([^"]+)"/g).map(match => match[1]))
  for (const link of help.matchAll(/href="#([^"]+)"/g)) assert.ok(ids.has(link[1]!), `missing chapter ${link[1]}`)
  for (const image of help.matchAll(/<img[^>]+src="(images\/[^"]+)"/g)) await access(new URL(`../public/help/${image[1]}`, import.meta.url))
  assert.match(help, /href="#generic-form"/)
  assert.match(help, /href="#operation-guide"/)
  assert.match(help, /href="#retention"/)
})
