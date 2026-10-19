import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { ApiFailure } from '../src/api.ts'
import { auditExportDiverged } from '../src/audit.ts'
import type { AuditFilters, AuditOptions } from '../src/audit.ts'
import { makeDiagnostic } from '../src/diagnostics.ts'

// 组件级恢复路径测试：复用 detail-loading.test.ts 的编译挂载 harness（compiler-sfc + 自定义 renderer，
// 模板不渲染、只驱动 setup 暴露的行为），覆盖 options 独立重试、错误编号/Retry-After 呈现、
// 导出与已应用快照分叉的确认弹窗。api 级的解码覆盖在 audit.test.ts（后端批），这里不重复。
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const dataUrl = (value: string) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`
const child = dataUrl('export default {render(){return null}}')
const clicks: number[] = []
// element-plus 桩：ElMessage/ElMessageBox 经 data:URL 模块隔离，只能通过 globalThis 回传记录。
const auditTestState = { messages: [] as [string, string][], confirms: [] as string[], decision: 'confirm' as 'confirm' | 'cancel' }
;(globalThis as Record<string, unknown>).__auditPanelTest = auditTestState
const element = dataUrl(`export const ElMessage={success(m){globalThis.__auditPanelTest.messages.push(['success',m])},error(m){globalThis.__auditPanelTest.messages.push(['error',m])},warning(m){globalThis.__auditPanelTest.messages.push(['warning',m])},info(m){globalThis.__auditPanelTest.messages.push(['info',m])}};export const ElMessageBox={async confirm(m){globalThis.__auditPanelTest.confirms.push(m);if(globalThis.__auditPanelTest.decision==='cancel')throw new Error('cancel')}}`)
const icons = dataUrl('export const Download={};export const Search={}')
const renderer = vue.createRenderer({ patchProp() {}, insert() {}, remove() {}, createElement() { return {} },
  createText() { return {} }, createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null } })
// AuditPanel.download 创建 <a> 触发浏览器下载；node 环境用最小 stub 记录点击。
Object.assign(globalThis, { document: { createElement: () => ({ click() { clicks.push(1) } }) } })
const flush = async () => { await Promise.resolve(); await vue.nextTick(); await Promise.resolve() }

const card = (code: string, extra: { status?: number; error_id?: string } = {}) =>
  makeDiagnostic({ origin: 'http', operation: 'audit', code, status: extra.status, error_id: extra.error_id })
const options: AuditOptions = { actors: [{ id: 'u1', username: 'hr1', display_name: '张三', role: 'operator' }], events: [], outcomes: [] }
const firstPage = { items: [{ id: 'a1', actor: 'hr1', event: 'login', description: '登录', outcome: 'success' }], total: 1, page: 1, page_size: 50 }

function fakeAuditApi() {
  const impl = {
    options: async (_signal?: AbortSignal): Promise<AuditOptions> => options,
    page: async () => firstPage,
    exportAll: async () => new Blob(['workbook']),
  }
  const calls = { pages: 0, exports: [] as AuditFilters[] }
  return {
    calls, impl,
    auditOptions: (signal: AbortSignal) => impl.options(signal),
    auditPage: (filters: AuditFilters, page: number, size: number, signal: AbortSignal) => { calls.pages++; return impl.page(filters, page, size, signal) },
    auditExport: (filters: AuditFilters, signal: AbortSignal) => { calls.exports.push(filters); return impl.exportAll(filters, signal) },
  }
}

async function mountPanel(api: ReturnType<typeof fakeAuditApi>, onUnauthorized?: () => void) {
  const filename = fileURLToPath(new URL('../src/components/AuditPanel.vue', import.meta.url))
  const expose = 'error,optionsError,optionsLoading,options,rows,actor,loadOptions,download,query,fetchPage,busy,exporting'
  const source = (await readFile(filename, 'utf8')).replace('</script>', `defineExpose({${expose}})\n</script>`)
  const compiled = compileScript(parse(source, { filename }).descriptor, { id: 'AuditPanel' })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
      const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(filename), specifier) : require.resolve(specifier)
      return `from '${specifier.endsWith('.vue') ? child : specifier === 'element-plus' ? element : specifier === '@element-plus/icons-vue' ? icons : pathToFileURL(resolved).href}'`
    })
  const Component = (await import(dataUrl(code))).default
  Component.render = () => null
  const component = vue.ref()
  const app = renderer.createApp({ render: () => vue.h(Component, { api, ref: component, onUnauthorized }) })
  app.mount({}); await flush()
  return { app, vm: component.value }
}

test('auditExportDiverged compares the live filters with the applied snapshot', () => {
  assert.equal(auditExportDiverged({}, {}), false)
  assert.equal(auditExportDiverged({ actor: 'u1' }, { actor: 'u1' }), false)
  assert.equal(auditExportDiverged({ actor: 'u1' }, {}), true)
  assert.equal(auditExportDiverged({}, { actor: 'u1' }), true)
})

test('an options failure no longer blocks the first page and can be retried', async () => {
  const api = fakeAuditApi()
  api.impl.options = async () => { throw new ApiFailure(card('NETWORK_ERROR'), undefined) }
  const { app, vm } = await mountPanel(api)
  try {
    assert.equal(vm.rows.length, 1, '筛选项失败时列表照常出第一页')
    assert.equal(vm.error, '', 'options 的失败不算列表失败')
    assert.ok(vm.optionsError.includes('无法连接本地服务'))
    api.impl.options = async () => options
    await vm.loadOptions(); await flush()
    assert.equal(vm.options.actors.length, 1)
    assert.equal(vm.optionsError, '')
  } finally { app.unmount(); await flush() }
})

test('audit failures surface retry seconds or the error id like the review drawer', async () => {
  const api = fakeAuditApi()
  api.impl.page = async () => { throw new ApiFailure(card('SERVICE_BUSY'), 30) }
  const { app, vm } = await mountPanel(api)
  try {
    assert.ok(vm.error.includes('服务器繁忙'))
    assert.ok(vm.error.includes('可在 30 秒后重试'))
    api.impl.exportAll = async () => { throw new ApiFailure(card('AUDIT_EXPORT_TOO_LARGE', { status: 422, error_id: 'e_export01' }), undefined) }
    await vm.download(); await flush()
    assert.ok(vm.error.includes('匹配记录超过10000条'), '导出超限走专属错误码文案')
    assert.ok(vm.error.includes('错误编号 e_export01'))
    assert.ok(!vm.error.includes('秒后重试'), '无 Retry-After 时不编造秒数')
  } finally { app.unmount(); await flush() }
})

test('export asks before diverging from the queried snapshot and honours cancel', async t => {
  const api = fakeAuditApi()
  t.mock.method(URL, 'createObjectURL', () => 'blob:audit-panel-test')
  t.mock.method(URL, 'revokeObjectURL', () => {})
  const { app, vm } = await mountPanel(api)
  try {
    assert.equal(auditTestState.confirms.length, 0)
    vm.actor = 'u1'; await flush()
    auditTestState.decision = 'cancel'
    await vm.download(); await flush()
    assert.equal(api.calls.exports.length, 0, '取消确认时不导出')
    assert.equal(auditTestState.confirms.length, 1)
    auditTestState.decision = 'confirm'
    await vm.download(); await flush()
    assert.deepEqual(api.calls.exports, [{ actor: 'u1' }], '确认后按当前（实时）筛选导出')
    assert.ok(auditTestState.messages.some(([kind, text]) => kind === 'success' && text === '已导出 Excel 文件。'))
    vm.actor = ''; await flush()
    const confirmsBefore = auditTestState.confirms.length
    await vm.download(); await flush()
    assert.equal(api.calls.exports.length, 2, '与快照一致时不弹确认直接导出')
    assert.equal(auditTestState.confirms.length, confirmsBefore, '第三次不新增确认弹窗')
    assert.equal(clicks.length, 2)
  } finally { auditTestState.decision = 'confirm'; app.unmount(); await flush() }
})

test('a 401 audit failure routes to the unauthorized event once', async () => {
  const api = fakeAuditApi()
  api.impl.page = async () => { throw new ApiFailure(card('UNAUTHORIZED', { status: 401 }), undefined) }
  let unauthorized = 0
  const { app } = await mountPanel(api, () => { unauthorized++ })
  try {
    assert.equal(unauthorized, 1, '会话过期离开审计页而不是留在内联错误')
  } finally { app.unmount(); await flush() }
})

test('an export still in flight at unmount never downloads or reports success', async () => {
  const api = fakeAuditApi()
  let release!: (blob: Blob) => void
  api.impl.exportAll = () => new Promise<Blob>(resolve => { release = () => resolve(new Blob(['late'])) })
  const clicksBefore = clicks.length, messagesBefore = auditTestState.messages.length
  const { app, vm } = await mountPanel(api)
  const pending = vm.download(); await flush()
  app.unmount(); release(); await pending; await flush()
  assert.equal(clicks.length, clicksBefore, '卸载后迟到的导出不再触发下载')
  assert.equal(auditTestState.messages.length, messagesBefore, '卸载后不再报成功')
})
