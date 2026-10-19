import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const dataUrl = (value: string) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`
const child = dataUrl('export default {render(){return null}}')
const element = dataUrl('export const ElMessage={error(){},warning(){},info(){}}; export const ElMessageBox={async confirm(){}}')
const icons = dataUrl('export const Crop={};export const Download={}')
const renderer = vue.createRenderer({ patchProp(){}, insert(){}, remove(){}, createElement(){return{}},
  createText(){return{}}, createComment(){return{}}, setText(){}, setElementText(){}, parentNode(){return null}, nextSibling(){return null} })
class Observer { constructor(...args: unknown[]) {} observe() {} disconnect() {} }
class FakeElement {
  dataset = {}; clientHeight = 100; scrollHeight = 100; overflowY = 'visible'; parentElement: FakeElement | null = null
  querySelector() { return null } scrollIntoView(options: unknown) {}
}
const frames = new Map<number, () => void>(); let frameId = 0
Object.assign(globalThis, { IntersectionObserver: Observer, ResizeObserver: Observer, HTMLElement: FakeElement,
  requestAnimationFrame: (callback: () => void) => { frames.set(++frameId, callback); return frameId },
  getComputedStyle: (element: FakeElement) => ({ overflowY: element.overflowY }),
  cancelAnimationFrame: (id: number) => { frames.delete(id) } })
const id = '11111111-2222-4333-8444-555555555555'
const task = { task_id: id, run_id: id, result_revision: 3, doc_type: 'MEDICAL_REPORT', page_count: 8, actual_source_page_count: 8, status: 'NEED_REVIEW' }
const flush = async () => { await Promise.resolve(); await vue.nextTick(); await Promise.resolve() }

async function mount(name: string, expose: string, props: Record<string, unknown>) {
  const filename = fileURLToPath(new URL(`../src/components/${name}.vue`, import.meta.url))
  const source = (await readFile(filename, 'utf8')).replace('</script>', `defineExpose({${expose}})\n</script>`)
  const compiled = compileScript(parse(source, { filename }).descriptor, { id: name })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
      const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(filename), specifier) : require.resolve(specifier)
      return `from '${specifier.endsWith('.vue') ? child : specifier === 'element-plus' ? element : specifier === '@element-plus/icons-vue' ? icons : pathToFileURL(resolved).href}'`
    })
  const Component = (await import(dataUrl(code))).default
  Component.render = () => null
  const state = vue.reactive(props), component = vue.ref()
  const app = renderer.createApp({ render: () => vue.h(Component, { ...state, ref: component }) })
  app.mount({}); await flush()
  return { app, vm: component.value, state }
}

async function preview() {
  const calls: { page: number; revision: number; signal: AbortSignal; resolve: () => void }[] = []
  const api = { preview: (current: typeof task, page: number, signal: AbortSignal) => new Promise(resolve => {
    calls.push({ page, revision: current.result_revision, signal, resolve: () => resolve({ blob: new Blob(['synthetic pixels']), corrected: true }) })
  }) }
  const mounted = await mount('SourcePreview', 'loadPage,onIntersect,goTo,entries,setPageRef,scrollViewportFor', { task: { ...task }, api, source: null, canWrite: true, active: true })
  return { ...mounted, calls, visible: (pages: number[]) => mounted.vm.onIntersect(pages.map(page => ({ isIntersecting: true, target: { dataset: { page: String(page) } } }))) }
}

test('preview bounds background requests and prioritizes the explicitly selected page', async () => {
  const { app, vm, calls, visible } = await preview()
  try {
    visible([1,2,3,4,5,6,7,8])
    assert.deepEqual(calls.map(c => c.page), [1,2])
    vm.goTo(8)
    calls[0]!.resolve(); await flush(); await flush()
    assert.deepEqual(calls.map(c => c.page), [1,2,8])
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush() }
})

test('same-page callers wait for the single in-flight request', async () => {
  const { app, vm, calls } = await preview()
  try {
    let done = false
    const waiting = vm.loadPage(1).then(() => { done = true })
    await flush(); assert.equal(done, false); assert.equal(calls.length, 1)
    calls[0]!.resolve(); await waiting
    assert.equal(done, true)
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush() }
})

test('closing a preview aborts active work and never starts pending pages', async () => {
  const { app, state, vm, calls, visible } = await preview()
  try {
    visible([1,2,3,4])
    state.active = false; await flush()
    assert.ok(calls.every(c => c.signal.aborted))
    const count = calls.length
    calls.forEach(c => c.resolve()); await flush(); await flush()
    assert.equal(calls.length, count)
    assert.ok(vm.entries.every((entry: { url: string }) => !entry.url))
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush() }
})

test('an old preview response cannot replace the next revision or release its request slot', async () => {
  const { app, state, vm, calls, visible } = await preview()
  try {
    visible([1,2,3])
    const old = [...calls]
    state.task = { ...task, result_revision: 4 }; await flush()
    assert.ok(old.every(c => c.signal.aborted))
    old.forEach(c => c.resolve()); await flush(); await flush()
    assert.ok(vm.entries.every((entry: { url: string }) => !entry.url))
    assert.equal(calls.filter(c => c.revision === 4).length, 2)
    calls.find(c => c.revision === 4 && c.page === 1)!.resolve(); await flush(); await flush()
    assert.equal(calls.filter(c => c.revision === 4).length, 3)
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush() }
})

test('a field selection loads once and keeps smooth location after the image is ready', async () => {
  const { app, state, vm, calls } = await preview()
  const scrolls: unknown[] = [], page = new FakeElement()
  page.scrollIntoView = options => { scrolls.push(options) }
  try {
    vm.setPageRef(page, 8)
    state.source = { page: 8, bbox: [.1,.2,.3,.4] }; await flush()
    calls.find(c => c.page === 8)!.resolve(); await flush()
    vm.entries[7].loaded = true; await flush()
    const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback())
    assert.deepEqual(scrolls, [{ behavior: 'smooth', block: 'center' }])
    assert.equal(calls.filter(c => c.page === 8).length, 1)
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush(); frames.clear() }
})

test('a tall responsive column is not mistaken for the actual scroll viewport', async () => {
  const { app, vm, calls } = await preview()
  try {
    const column = new FakeElement(), drawer = new FakeElement()
    column.overflowY = 'auto'; column.clientHeight = column.scrollHeight = 10000; column.parentElement = drawer
    drawer.overflowY = 'auto'; drawer.clientHeight = 600; drawer.scrollHeight = 12000
    assert.equal(vm.scrollViewportFor(column), drawer)
    column.clientHeight = 500
    assert.equal(vm.scrollViewportFor(column), column)
  } finally { app.unmount(); calls.forEach(c => c.resolve()); await flush() }
})

test('opening a drawer with its task in one update reads the result only once and retains dirty drafts', async () => {
  let calls = 0
  const api = { result: async () => { calls++; return { ...task, fields: [] } } }
  const { app, vm, state } = await mount('TaskResultDrawer', 'result,dirty,stale',
    { open: false, task: null, api, monitor: {}, previews: new Map(), canWrite: true, catalogue: [] })
  try {
    state.open = true; state.task = { ...task }; await flush(); await flush()
    assert.equal(calls, 1)
    vm.dirty = true
    state.task = { ...task, result_revision: 4 }; await flush()
    assert.equal(calls, 1); assert.equal(vm.dirty, true); assert.equal(vm.stale, true)
    assert.equal(vm.result.result_revision, 3)
  } finally { app.unmount() }
})
