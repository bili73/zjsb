import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { BusinessApi } from '../src/api.ts'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const dataUrl = (value: string) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`
const element = dataUrl('let hook;export function setConfirmHook(value){hook=value};export const ElMessage={error(){},warning(){},info(){},success(){}}; export const ElMessageBox={async confirm(){await hook?.()}}')
const { setConfirmHook } = await import(element)
const child = dataUrl('export default {render(){return null}}')
const icons = dataUrl('export const Download={render(){return null}}; export const CircleClose=Download,Delete=Download,RefreshRight=Download,UploadFilled=Download,User=Download,View=Download,WarningFilled=Download')
const renderer = vue.createRenderer({ patchProp(){}, insert(){}, remove(){}, createElement(){return{}},
  createText(){return{}}, createComment(){return{}}, setText(){}, setElementText(){}, parentNode(){return null}, nextSibling(){return null} })
// TaskResultDrawer 保存失败指位（revealAnchor）需要 document.getElementById 与 matchMedia；与 detail-loading harness 同款桩，返回 null 即不滚动。
Object.assign(globalThis, { matchMedia: () => ({ matches: false }), document: { getElementById: () => null } })

async function mount(name: string, expose: string, props: Record<string, unknown>) {
  const filename = fileURLToPath(new URL(`../src/components/${name}.vue`, import.meta.url))
  const source = (await readFile(filename, 'utf8')).replace('</script>', `defineExpose({${expose}})\n</script>`)
  const compiled = compileScript(parse(source, { filename }).descriptor, { id: name })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
      const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(filename), specifier) : require.resolve(specifier)
      return `from '${specifier.endsWith('.vue') ? child : specifier.endsWith('.png') ? dataUrl("export default 'test-logo'") : specifier === 'element-plus' ? element : specifier === '@element-plus/icons-vue' ? icons : pathToFileURL(resolved).href}'`
    })
  const Component = (await import(dataUrl(code))).default
  Component.render = () => null
  const app = renderer.createApp(Component, props)
  return { app, vm: app.mount({}) }
}

const id = '11111111-2222-4333-8444-555555555555'
const task = { task_id: id, run_id: id, result_revision: 3, doc_type: 'DIPLOMA', status: 'COMPLETED', export_ready: true }
test('actual detail save keeps dirty draft and current result on a busy response', async () => {
  const calls: string[] = []
  const api = new BusinessApi((async url => {
    calls.push(String(url))
    return new Response(JSON.stringify({ code: 'SERVICE_BUSY' }), { status: 503, headers: { 'Retry-After': '2' } })
  }) as typeof fetch)
  const { app, vm } = await mount('TaskResultDrawer', 'result,dirty,stale,reviewError,saving,saveReview',
    { open: false, task: null, api, monitor: {}, previews: new Map(), canWrite: true, catalogue: [] })
  try {
    const original = { ...task, fields: [{ key: 'name', value: '合成已保存姓名' }] }
    vm.result = original; vm.dirty = true
    await vm.saveReview({ run_id: id, expected_revision: 3, fields: { name: '合成草稿姓名' } })
    assert.equal(vm.dirty, true)
    assert.equal(vm.stale, false)
    assert.equal(vm.saving, false)
    assert.deepEqual(vm.result, original)
    assert.match(vm.reviewError, /服务器繁忙/)
    assert.deepEqual(calls, [`/api/v1/tasks/${id}/review`])
  } finally { app.unmount() }
})

test('actual export controls retain selection mode and show retry guidance', async () => {
  let calls = 0
  const api = new BusinessApi((async () => {
    calls++
    return new Response(JSON.stringify({ code: 'OPERATION_THROTTLED' }), { status: 429, headers: { 'Retry-After': '2' } })
  }) as typeof fetch)
  const selected = [task]
  const { app, vm } = await mount('ExportControls', 'mode,busy,message,run', { api, tasks: selected, selected, batchId: id, canWrite: true })
  try {
    vm.mode = 'selection'
    await vm.run()
    assert.equal(vm.mode, 'selection')
    assert.deepEqual(selected, [task])
    assert.equal(vm.busy, false)
    assert.match(vm.message, /2 秒后重试/)
    assert.equal(calls, 1)
  } finally { app.unmount() }
})

test('login countdown blocks repeated submission, clears password and never submits automatically', async () => {
  const previous = globalThis.fetch
  let requests = 0
  globalThis.fetch = async () => {
    requests++
    return new Response(JSON.stringify({ code: 'LOGIN_THROTTLED' }), { status: 429, headers: { 'Retry-After': '3' } })
  }
  const { app, vm } = await mount('LoginGate', 'username,password,verify,retrySeconds,retryUntil,clockNow',
    { engine: { state: { connection: 'connected' } } })
  try {
    vm.username = 'synthetic'; vm.password = 'synthetic password'
    await vm.verify()
    assert.equal(vm.password, '')
    assert.equal(vm.retrySeconds, 3)
    vm.password = 'synthetic retry'
    await vm.verify()
    assert.equal(requests, 1)
    vm.clockNow = vm.retryUntil
    assert.equal(vm.retrySeconds, 0)
    assert.equal(requests, 1)
    await vm.verify()
    assert.equal(requests, 2)
  } finally { app.unmount(); globalThis.fetch = previous }
})

test('task row deletion removes only matching selection and notifies preview cleanup', async () => {
  const first = { ...task, task_id: crypto.randomUUID(), batch_id: id }, peer = { ...task, task_id: crypto.randomUUID(), batch_id: id }
  const removed: string[] = []
  const monitor = { state: { dateRange: null, entries: {}, order: [], pending: {} }, setDateRange(){},
    async deleteTask(batch: string, version: typeof first) {
      assert.equal(batch, id); assert.equal(version.task_id, first.task_id)
      return { task_id: version.task_id, batch_id: batch, batch_deleted: false, cleanup_pending: false }
    } }
  const { app, vm } = await mount('BatchBoard', 'selected,deleteTask', { monitor, canWrite: true, isAdmin: false,
    api: null, uploadReset: 0, catalogue: [], onTaskDeleted: (_batch: string, taskId: string) => removed.push(taskId) })
  try {
    vm.selected[id] = [first, peer]
    await vm.deleteTask(id, first)
    assert.deepEqual(vm.selected[id].map((t: typeof peer) => t.task_id), [peer.task_id])
    assert.deepEqual(removed, [first.task_id])
  } finally { app.unmount() }
})

test('cancelling deletion or leaving its confirmation never sends a delete request', async () => {
  for (const leave of [false, true]) {
    let release: (() => void) | undefined, requests = 0
    const monitor = { state: { dateRange: null, entries: {}, order: [], pending: {} }, setDateRange(){},
      async deleteTask() { requests++; throw new Error('Must not delete') } }
    setConfirmHook(leave ? () => new Promise<void>(resolve => { release = resolve }) :
      () => Promise.reject(new Error('cancel')))
    const { app, vm } = await mount('BatchBoard', 'deleteTask', { monitor, canWrite: true, isAdmin: false,
      api: null, uploadReset: 0, catalogue: [] })
    try {
      const pending = vm.deleteTask(id, task)
      if (leave) { app.unmount(); release?.() }
      await pending
      assert.equal(requests, 0)
    } finally { if (!leave) app.unmount(); setConfirmHook(undefined) }
  }
})
