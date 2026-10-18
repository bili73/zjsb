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
const element = dataUrl('export const ElMessage={error(){},warning(){},info(){}}; export const ElMessageBox={async confirm(){}}')
const child = dataUrl('export default {render(){return null}}')
const icons = dataUrl('export const Download={render(){return null}}')
const renderer = vue.createRenderer({ patchProp(){}, insert(){}, remove(){}, createElement(){return{}},
  createText(){return{}}, createComment(){return{}}, setText(){}, setElementText(){}, parentNode(){return null}, nextSibling(){return null} })

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
