import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { rangeSuffix } from '../src/batchCalendar.ts'
import type { Task } from '../src/business.ts'

// 视觉审查 #19/#20：rangeSuffix 是纯函数直接断言；batchTitle 用 detail-loading/audit-panel 同款
// 编译挂载 harness 驱动 setup（模板渲染 no-op）。分页器 v-if 与工具栏阅读顺序属模板级改动，
// 本 harness 无法断言 DOM，由 vue-tsc 与人工验收覆盖。
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const dataUrl = (value: string) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`
const child = dataUrl('export default {render(){return null}}')
const element = dataUrl(`export const ElMessage={success(){},error(){},warning(){},info(){}};export const ElMessageBox={async confirm(){throw new Error('cancel')}}`)
const icons = dataUrl('export const CircleClose={},Delete={},RefreshRight={},UploadFilled={},User={},View={},WarningFilled={}')
const renderer = vue.createRenderer({ patchProp() {}, insert() {}, remove() {}, createElement() { return {} },
  createText() { return {} }, createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null } })
const flush = async () => { await Promise.resolve(); await vue.nextTick(); await Promise.resolve() }

type FakeBatch = { batch_id: string; display_name?: string; created_at?: string }
type FakeEntry = { batch: FakeBatch | null; tasks: unknown[]; tasksLoaded: boolean; expanded: boolean }

function fakeMonitor(entries: Record<string, FakeEntry>) {
  return { state: { dateRange: null, entries, order: Object.keys(entries), listedIds: [], pending: {} }, setDateRange() {} }
}

async function mountBoard(monitor: ReturnType<typeof fakeMonitor>) {
  const filename = fileURLToPath(new URL('../src/components/BatchBoard.vue', import.meta.url))
  const source = (await readFile(filename, 'utf8')).replace('</script>', `defineExpose({batchTitle, visibleTasks, taskNumbers, missingOnly, disputedOnly})\n</script>`)
  const compiled = compileScript(parse(source, { filename }).descriptor, { id: 'BatchBoard' })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
      const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(filename), specifier) : require.resolve(specifier)
      return `from '${specifier.endsWith('.vue') ? child : specifier === 'element-plus' ? element : specifier === '@element-plus/icons-vue' ? icons : pathToFileURL(resolved).href}'`
    })
  const Component = (await import(dataUrl(code))).default
  Component.render = () => null
  const component = vue.ref()
  const app = renderer.createApp({ render: () => vue.h(Component, { monitor, canWrite: false, isAdmin: false, api: null, uploadReset: 0, catalogue: [], ref: component }) })
  app.mount({}); await flush()
  return { app, vm: component.value }
}

test('rangeSuffix keeps week wording to the anchored week view', () => {
  assert.equal(rangeSuffix('week', true), '（UTC+8，周一至周日）')
  assert.equal(rangeSuffix('day', true), '（UTC+8）')
  assert.equal(rangeSuffix('month', true), '（UTC+8）')
  assert.equal(rangeSuffix('week', false), '（UTC+8）')
})

test('batchTitle falls back to a minute-precision stamp, not the uuid prefix', async () => {
  const entry = (batch: FakeBatch | null): FakeEntry => ({ batch, tasks: [], tasksLoaded: false, expanded: false })
  const { app, vm } = await mountBoard(fakeMonitor({
    named: entry({ batch_id: 'named', display_name: '混合材料 · 张三', created_at: '2026-10-19T08:30:00Z' }),
    emptyName: entry({ batch_id: 'e', display_name: '', created_at: '2026-10-19T08:30:00Z' }),
    sameDayA: entry({ batch_id: 'a', created_at: '2026-10-19T08:30:00Z' }),
    sameDayB: entry({ batch_id: 'b', created_at: '2026-10-19T09:05:00Z' }),
    unparseable: entry({ batch_id: 'c', created_at: 'not-a-date' }),
    creating: entry(null),
  }))
  try {
    assert.equal(vm.batchTitle('named'), '混合材料 · 张三', 'display_name 优先')
    assert.equal(vm.batchTitle('emptyName'), '未命名批次 2026-10-19 16:30', '空 display_name 走回退')
    assert.equal(vm.batchTitle('sameDayA'), '未命名批次 2026-10-19 16:30')
    assert.equal(vm.batchTitle('sameDayB'), '未命名批次 2026-10-19 17:05', '同日多批可区分')
    assert.equal(vm.batchTitle('unparseable'), '未命名批次', '无效 created_at 不留「—」残留')
    assert.equal(vm.batchTitle('creating'), '未命名批次')
    assert.equal(vm.batchTitle('missing'), '未命名批次')
  } finally { app.unmount(); await flush() }
})

test('batch board keeps full-batch file numbers through filtering, refresh and file changes', async () => {
  const task = (id: string, name: string, code?: 'MISSING' | 'DISPUTED'): Task => ({
    task_id: id, file_name: name, run_id: `run-${id}`, result_revision: 1, cancel_requested: false,
    status: 'NEED_REVIEW', doc_type: 'DIPLOMA', page_count: 1, pages: [], export_ready: !code,
    export_blockers: code ? [{ field: 'major', code }] : [],
  })
  const tasks = [task('ten', '10.jpg', 'MISSING'), task('two', '2.jpg', 'DISPUTED'), task('one', '1.jpg')]
  const entry = (files: Task[]): FakeEntry => ({ batch: null, tasks: files, tasksLoaded: true, expanded: true })
  const monitor = vue.reactive(fakeMonitor({ first: entry(tasks), second: entry([task('other', '9.jpg')]) }))
  monitor.state.listedIds = ['first', 'second']
  const { app, vm } = await mountBoard(monitor)
  const ids = (batch = 'first') => vm.visibleTasks(batch).map((item: Task) => item.task_id)
  try {
    assert.deepEqual(ids(), ['one', 'two', 'ten'])
    assert.deepEqual(vm.taskNumbers, { one: 1, two: 2, ten: 3, other: 1 })
    vm.missingOnly.first = true
    assert.deepEqual(ids(), ['ten'])
    assert.equal(vm.taskNumbers.ten, 3, 'filtering must retain the complete-batch sequence')
    vm.missingOnly.first = false
    vm.disputedOnly.first = true
    assert.deepEqual(ids(), ['two'])
    assert.equal(vm.taskNumbers.two, 2)
    vm.disputedOnly.first = false
    monitor.state.entries.first!.tasks = [...tasks].reverse().map(item => ({ ...item,
      status: 'COMPLETED', run_id: `rerun-${item.task_id}`, result_revision: 2 }))
    assert.deepEqual(ids(), ['one', 'two', 'ten'])
    assert.equal(vm.taskNumbers.ten, 3)
    monitor.state.entries.first!.tasks.push(task('three', '3.jpg'))
    assert.deepEqual(ids(), ['one', 'two', 'three', 'ten'])
    assert.equal(vm.taskNumbers.ten, 4)
    monitor.state.entries.first!.tasks = monitor.state.entries.first!.tasks.filter((item: Task) => item.task_id !== 'two')
    assert.deepEqual(ids(), ['one', 'three', 'ten'])
    assert.equal(vm.taskNumbers.ten, 3)
    assert.deepEqual(ids('second'), ['other'])
    assert.equal(vm.taskNumbers.other, 1)
    assert.deepEqual(ids('not-loaded'), [])
    assert.deepEqual(tasks.map(item => item.task_id), ['ten', 'two', 'one'], 'source arrays stay untouched')
  } finally { app.unmount(); await flush() }
})
