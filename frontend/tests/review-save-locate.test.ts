import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

// 保存校验失败的指位（视觉审查 #14 剩余）：ReviewEditor 按错误码展开对应折叠面板并滚动到出错块。
// 模板从不渲染（render = () => null），指位行为通过登记的锚点元素与 openPanels 状态断言。
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath = fileURLToPath(new URL('../src/components/ReviewEditor.vue', import.meta.url))
const rawSource = await readFile(sourcePath, 'utf8')
const source = rawSource.replace('</script>',
  'defineExpose({save, message, openPanels, added, addedMembers, findings, generic, coverageEnabled, checkedPages, coverageReason, summaryEnabled, summaryReason, values})\n</script>')
const compiled = compileScript(parse(source, { filename: sourcePath }).descriptor, { id: 'review-save-locate-test' })
const dataUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const elementStub = dataUrl('export const ElMessageBox = { confirm: async () => {} }')
const iconStub = dataUrl('export const InfoFilled = {}')
const code = ts.transpileModule(compiled.content, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
  if (specifier === 'element-plus') return `from '${elementStub}'`
  if (specifier === '@element-plus/icons-vue') return `from '${iconStub}'`
  const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(sourcePath), specifier) : require.resolve(specifier)
  return `from '${pathToFileURL(resolved).href}'`
})
const Component = (await import(dataUrl(code))).default
Component.render = () => null
const renderer = vue.createRenderer({
  patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
  createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null },
})

class FakeAnchor {
  tabIndex = 0
  scrolled: unknown = null
  focused: unknown = null
  readonly classes = new Set<string>()
  scrollIntoView(options: unknown) { this.scrolled = options }
  focus(options: unknown) { this.focused = options }
  get offsetWidth() { return 0 }
  get classList() {
    return { add: (name: string) => this.classes.add(name), remove: (name: string) => this.classes.delete(name), has: (name: string) => this.classes.has(name) }
  }
}
// revealAnchor 依赖 document.getElementById 与 matchMedia；未登记的 id 返回 null（与真实 DOM 一致）。
const anchors = new Map<string, FakeAnchor>()
Reflect.set(globalThis, 'matchMedia', () => ({ matches: false }))
Reflect.set(globalThis, 'document', { getElementById: (id: string) => anchors.get(id) ?? null })

const id = '11111111-2222-4333-8444-555555555555'
const base = { task_id: id, run_id: id, result_revision: 3 }
const medical = () => ({ ...base, doc_type: 'MEDICAL_REPORT', fields: [], items: [], report_summary: { declared_count: 2, scope: 'follow_up_required', findings: [{ finding_id: 'f1', text: '建议复查' }] } })
const flush = async () => { await Promise.resolve(); await vue.nextTick(); await Promise.resolve() }

async function mountEditor(result: Record<string, unknown>) {
  // 模板 ref 拿公开代理：exposed refs 在代理上自动解包（与 detail-loading harness 同款；_instance.exposed 不解包）。
  const component = vue.ref()
  const app = renderer.createApp({ render: () => vue.h(Component, { result, canWrite: true, busy: false, pageCount: 2, ref: component }) })
  app.mount({})
  await flush()
  return { app, vm: component.value }
}

test('deleting a list entry without the summary fix jumps to the summary block', async () => {
  anchors.set('rev-summary', new FakeAnchor())
  const { app, vm } = await mountEditor(medical())
  try {
    vm.findings[0].removed = true
    vm.save()
    await flush()
    assert.equal(vm.message, '已新增或删除清单条目：请展开「清单声明数 / 增删条目」，勾选修正报告清单并填写理由与来源页。')
    assert.ok(vm.openPanels.includes('summary-edit'))
    const anchor = anchors.get('rev-summary')!
    assert.deepEqual(anchor.scrolled, { behavior: 'smooth', block: 'center' })
    assert.equal(anchor.tabIndex, -1)
    assert.deepEqual(anchor.focused, { preventScroll: true })
    assert.ok(anchor.classList.has('jump-flash'))
  } finally { anchors.clear(); app.unmount() }
})

test('an incomplete added item jumps to the offending added row', async () => {
  anchors.set('rev-added-0', new FakeAnchor())
  const { app, vm } = await mountEditor(medical())
  try {
    vm.added.push({ name: '', alias: '', category: '', result_raw: '', unit: '', reference_range: '', reported_abnormal_marker: '', risk_grade: '', diagnosis: '' })
    vm.save()
    await flush()
    assert.equal(vm.message, '新增检测项目需要项目名称和检测结果。')
    assert.ok(vm.openPanels.includes('items'))
    assert.deepEqual(anchors.get('rev-added-0')!.scrolled, { behavior: 'smooth', block: 'center' })
  } finally { anchors.clear(); app.unmount() }
})

test('an incomplete coverage declaration jumps to the coverage block', async () => {
  anchors.set('rev-coverage', new FakeAnchor())
  const { app, vm } = await mountEditor(medical())
  try {
    vm.coverageEnabled = true
    vm.save()
    await flush()
    assert.equal(vm.message, '全页覆盖确认：请勾选全部页面并填写核对依据。')
    assert.ok(vm.openPanels.includes('coverage'))
    assert.deepEqual(anchors.get('rev-coverage')!.scrolled, { behavior: 'smooth', block: 'center' })
  } finally { anchors.clear(); app.unmount() }
})

test('a masked generic full text jumps to the generic block without opening panels', async () => {
  anchors.set('rev-generic', new FakeAnchor())
  const { app, vm } = await mountEditor({ ...base, doc_type: 'GENERIC', fields: [], items: [] })
  try {
    vm.generic.full_text = '＊＊＊'
    vm.save()
    await flush()
    assert.equal(vm.message, '不能把掩码当作原始值提交。未改的掩码将跳过；需修正时请查看原件并输入完整值。')
    assert.deepEqual(anchors.get('rev-generic')!.scrolled, { behavior: 'smooth', block: 'center' })
    assert.deepEqual(vm.openPanels, [])
  } finally { anchors.clear(); app.unmount() }
})

test('an incomplete added member jumps to the new-members block', async () => {
  anchors.set('rev-new-members', new FakeAnchor())
  const { app, vm } = await mountEditor({ ...base, doc_type: 'HOUSEHOLD_REGISTER', fields: [], items: [], members: [] })
  try {
    vm.addedMembers.push({ fields: {}, source_page: 1 })
    vm.save()
    await flush()
    assert.equal(vm.message, '新增成员需要姓名，且原件页必须在 1 到总页数之间。')
    assert.ok(vm.openPanels.includes('new-members'))
    assert.deepEqual(anchors.get('rev-new-members')!.scrolled, { behavior: 'smooth', block: 'center' })
  } finally { anchors.clear(); app.unmount() }
})

test('enabling the summary fix without a reason names the cause and jumps to the summary block', async () => {
  anchors.set('rev-summary', new FakeAnchor())
  const { app, vm } = await mountEditor(medical())
  try {
    vm.summaryEnabled = true
    vm.save()
    await flush()
    assert.equal(vm.message, '修正报告清单需要核对依据与有效来源页。')
    assert.ok(vm.openPanels.includes('summary-edit'))
    assert.deepEqual(anchors.get('rev-summary')!.scrolled, { behavior: 'smooth', block: 'center' })
  } finally { anchors.clear(); app.unmount() }
})

test('a masked field value keeps the message but never jumps to a guessed block', async () => {
  anchors.set('rev-summary', new FakeAnchor())
  const { app, vm } = await mountEditor({ ...base, doc_type: 'DIPLOMA', fields: [{ key: 'name', label: '姓名', value: '' }] })
  try {
    vm.values.name = '***'
    vm.save()
    await flush()
    assert.equal(vm.message, '不能把掩码当作原始值提交。未改的掩码将跳过；需修正时请查看原件并输入完整值。')
    assert.equal(anchors.get('rev-summary')!.scrolled, null)
    assert.deepEqual(vm.openPanels, [])
  } finally { anchors.clear(); app.unmount() }
})

test('a valid save emits without any message or jump', async () => {
  const { app, vm } = await mountEditor(medical())
  try {
    vm.save()
    await flush()
    assert.equal(vm.message, '')
    assert.ok([...anchors.values()].every(anchor => anchor.scrolled === null))
    assert.deepEqual(vm.openPanels, [])
  } finally { anchors.clear(); app.unmount() }
})

test('the anchors named by the locate mapping exist in the template', async () => {
  for (const anchor of ['id="rev-summary"', 'id="rev-new-members"', 'id="rev-coverage"', 'id="rev-generic"']) {
    assert.ok(rawSource.includes(anchor), anchor)
  }
  assert.ok(rawSource.includes(':id="`rev-added-${index}`"'), 'rev-added rows must carry ids')
  const drawerSource = await readFile(fileURLToPath(new URL('../src/components/TaskResultDrawer.vue', import.meta.url)), 'utf8')
  assert.ok(drawerSource.includes('id="drawer-review-error"'), 'drawer alert must carry its id')
})
