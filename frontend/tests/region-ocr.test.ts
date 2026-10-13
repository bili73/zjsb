import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { BusinessApi } from '../src/api.ts'
import { mostVisiblePage, pointInImage, regionBox } from '../src/regionOcr.ts'
import type { Task } from '../src/business.ts'

test('display scaling and reverse drags retain normalized source coordinates', () => {
  for (const scale of [1, .5, 2]) {
    const rect = { left: 17, top: 43, width: 1000 * scale, height: 600 * scale }
    const a = pointInImage(17 + 750 * scale, 43 + 480 * scale, rect)
    const b = pointInImage(17 + 250 * scale, 43 + 120 * scale, rect)
    assert.deepEqual(regionBox(a, b), [.25, .2, .75, .8])
    assert.deepEqual(pointInImage(-20, 2000, rect), { x: 0, y: 1 })
  }
})
test('actual visible page wins over old jump page, with toolbar clipping and tie fallback', () => {
  const pages = [{ page: 1, top: -300, bottom: 200 }, { page: 2, top: 210, bottom: 710 }, { page: 3, top: 720, bottom: 1220 }]
  assert.equal(mostVisiblePage(pages, 150, 650, 1), 2)
  assert.equal(mostVisiblePage(pages, 150, 650, 3), 2)
  assert.equal(mostVisiblePage(pages, 2000, 2100, 3), 3)
  assert.equal(mostVisiblePage([{ page: 1, top: 0, bottom: 100 }, { page: 2, top: 100, bottom: 200 }], 0, 200, 2), 2)
})
const task = { task_id: crypto.randomUUID(), run_id: crypto.randomUUID(), result_revision: 3, page_count: 2, doc_type: 'DIPLOMA' } as Task
test('general OCR omits field binding and checks echoed selection, retaining legacy requests', async () => {
  const box: [number, number, number, number] = [.1, .2, .8, .5]
  let mismatch = false
  const client = new BusinessApi(async (input, init) => {
    assert.equal(String(input), `/api/v1/tasks/${task.task_id}/ocr-region`)
    const body = JSON.parse(String(init?.body))
    assert.equal(body.run_id, task.run_id); assert.equal(body.expected_revision, 3)
    assert.equal(body.page, 2); assert.deepEqual(body.bbox, box)
    assert.ok(!Object.hasOwn(body, 'field_key') || body.field_key === 'certificate_no')
    return Response.json({ task_id: task.task_id, run_id: task.run_id, result_revision: mismatch ? 4 : 3,
      field_key: body.field_key ?? null, page: 2, bbox: box, text: '00123\n合成文字', confidence: .9 })
  })
  for (const field of [null, 'certificate_no']) assert.deepEqual(await client.ocrRegion(task, field, 2, box, new AbortController().signal), { text: '00123\n合成文字', confidence: .9 })
  mismatch = true
  await assert.rejects(client.ocrRegion(task, null, 2, box, new AbortController().signal), error => (error as Error).message === 'INVALID_RESPONSE')
})

// Actual SFC setup/lifecycle code in a renderless Vue host.
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath = fileURLToPath(new URL('../src/components/RegionOcrDialog.vue', import.meta.url))
const source = (await readFile(sourcePath, 'utf8')).replace('</script>', 'defineExpose({recognize,copyResult,page,text,bbox,image,ready,error,textInput,copying})\n</script>')
const compiled = compileScript(parse(source, { filename: sourcePath }).descriptor, { id: 'source-region-test' })
const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
  .replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
    const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(sourcePath), specifier) : require.resolve(specifier)
    return `from '${pathToFileURL(resolved).href}'`
  })
  // @element-plus/icons-vue 只有 CJS 产物，node 静态分析不出命名导出，改为默认导入再解构。
  .replace(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]*@element-plus\/icons-vue[^'"]*)['"]/g,
    (_: string, names: string, resolved: string) => `import __epIcons from '${resolved}'; const { ${names.trim()} } = __epIcons`)
const Dialog = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
Dialog.render = () => null
const renderer = vue.createRenderer({ patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
  createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null } })
function mount(extra: object = {}) {
  const props = { open: true, canWrite: true, task, initialPage: 1,
    api: { preview: async () => ({ blob: new Blob(['synthetic']), corrected: true }), ocrRegion: async () => ({ text: '00123', confidence: .8 }) }, ...extra }
  const app = renderer.createApp(Dialog, props); app.mount({})
  return { app, exposed: app._instance.exposed, props: app._instance.props }
}
function clipboard(writeText?: (text: string) => Promise<void>) {
  Object.defineProperty(globalThis, 'navigator', { value: { clipboard: writeText ? { writeText } : undefined }, configurable: true })
}
test('late OCR text is discarded on close, account, page, task, revision, permission or unmount', async () => {
  for (const change of ['close', 'client', 'page', 'task', 'revision', 'permission', 'unmount']) {
    const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<{ text: string; confidence: number }>()
    const api = { preview: async () => ({ blob: new Blob(['synthetic']), corrected: true }), ocrRegion: async () => { entered.resolve(); return release.promise } }
    const h = mount({ api })
    try {
      await vue.nextTick(); await Promise.resolve()
      h.exposed.image.value = { naturalWidth: 1000, naturalHeight: 600 }
      h.exposed.ready.value = true; h.exposed.bbox.value = [0, 0, 1, 1]
      const pending = h.exposed.recognize(); await entered.promise
      if (change === 'close') h.props.open = false
      if (change === 'client') h.props.api = { ...api }
      if (change === 'page') h.exposed.page.value = 2
      if (change === 'task') h.props.task = { ...task, task_id: crypto.randomUUID() }
      if (change === 'revision') h.props.task = { ...task, result_revision: 4 }
      if (change === 'permission') h.props.canWrite = false
      if (change === 'unmount') h.app.unmount()
      release.resolve({ text: 'PRIVATE_OLD_TEXT', confidence: .9 }); await pending
      assert.equal(h.exposed.text.value, '', change)
    } finally { if (change !== 'unmount') h.app.unmount() }
  }
})
test('dialog starts at current PDF page and copies edited multiline text without closing', async () => {
  let selectedPage = 0, copied = '', closes = 0
  clipboard(async text => { copied = text })
  const h = mount({ initialPage: 2, onCancel: () => { closes++ },
    api: { preview: async (_t: Task, page: number) => { selectedPage = page; return { blob: new Blob(['synthetic']), corrected: true } },
      ocrRegion: async (_t: Task, field: string | null, page: number) => { assert.equal(field, null); assert.equal(page, 2); return { text: '00123\n原始文字', confidence: .4 } } } })
  try {
    await vue.nextTick(); await Promise.resolve()
    assert.equal(selectedPage, 2); assert.equal(h.exposed.page.value, 2)
    h.exposed.image.value = { naturalWidth: 1000, naturalHeight: 600 }; h.exposed.ready.value = true; h.exposed.bbox.value = [0, 0, 1, 1]
    await h.exposed.recognize(); assert.equal(h.exposed.text.value, '00123\n原始文字')
    h.exposed.text.value = '00124\n人工核对文字'; await h.exposed.copyResult()
    assert.equal(copied, '00124\n人工核对文字'); assert.equal(closes, 0)
    assert.equal(h.app._instance.emitted?.apply, undefined)
  } finally { h.app.unmount() }
})
test('blocked or unavailable clipboard keeps text and selects it for manual copying', async () => {
  for (const unavailable of [false, true]) {
    clipboard(unavailable ? undefined : async () => { throw new Error('denied') })
    let closes = 0, selects = 0
    const h = mount({ onCancel: () => { closes++ } })
    try {
      await vue.nextTick(); await Promise.resolve(); h.exposed.text.value = '00123\n保留文字'
      h.exposed.textInput.value = { focus() {}, select() { selects++ } }
      await h.exposed.copyResult()
      assert.equal(closes, 0); assert.equal(selects, 1); assert.equal(h.exposed.text.value, '00123\n保留文字')
      assert.match(h.exposed.error.value, /Ctrl\+C/); assert.equal(h.exposed.copying.value, false)
    } finally { h.app.unmount() }
  }
})
test('copy reentry is blocked and late completion cannot disturb a closed dialog', async () => {
  const done = Promise.withResolvers<void>(); let calls = 0, closes = 0
  clipboard(async () => { calls++; return done.promise })
  const h = mount({ onCancel: () => { closes++ } })
  try {
    await vue.nextTick(); await Promise.resolve(); h.exposed.text.value = 'old text'
    const pending = h.exposed.copyResult(); await h.exposed.copyResult(); assert.equal(calls, 1)
    h.props.open = false; await h.exposed.copyResult(); assert.equal(calls, 1)
    done.resolve(); await pending
    // 关闭触发 invalidate（generation 递增、text 清空），迟到的复制完成不得再产生任何副作用。
    assert.equal(closes, 0); assert.equal(h.exposed.copying.value, false)
  } finally { h.app.unmount() }
})
