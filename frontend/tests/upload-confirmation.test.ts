import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { ApiFailure } from '../src/api.ts'
import { makeDiagnostic } from '../src/diagnostics.ts'

// Compile the real SFC and exercise its Vue lifecycle, including the await before upload.
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath = fileURLToPath(new URL('../src/components/UploadPanel.vue', import.meta.url))
const source = (await readFile(sourcePath, 'utf8')).replace('</script>',
  'defineExpose({submit, fileList, personPackage, manualType, submitting, cancelSubmit, docType, invalidReason, photoOnly})\n</script>')
const compiled = compileScript(parse(source, { filename: sourcePath }).descriptor, { id: 'upload-confirmation-test' })
const dataUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const elementStub = dataUrl(`
export const ElMessageBox = { confirm: (...args) => globalThis.uploadTestConfirm(...args) };
export const ElMessage = { info(){}, warning(){}, error(){}, success(){} };
`)
const code = ts.transpileModule(compiled.content, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
  if (specifier === 'element-plus') return `from '${elementStub}'`
  const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(sourcePath), specifier)
    : specifier === '@element-plus/icons-vue' ? require.resolve('@element-plus/icons-vue/dist/index.js')
      : require.resolve(specifier)
  return `from '${pathToFileURL(resolved).href}'`
})
const Component = (await import(dataUrl(code))).default
Component.render = () => null
const renderer = vue.createRenderer({
  patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
  createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null },
})

function harness(target?: { batch_id: string; package_revision: number; person_name: string }) {
  const confirmations: ReturnType<typeof Promise.withResolvers>[] = []
  Reflect.set(globalThis, 'uploadTestConfirm', () => {
    const deferred = Promise.withResolvers()
    confirmations.push(deferred)
    return deferred.promise
  })
  const submissions: { files: File[]; type: string; options: { targetBatch?: typeof target; fileTypes?: string[] } }[] = []
  const monitor = {
    start() {},
    async submitUpload(files: File[], type: string, _abnormal: boolean, _signal: AbortSignal,
      options: { targetBatch?: typeof target; fileTypes?: string[] }) {
      submissions.push({ files, type, options })
      return { batch_id: 'accepted', task_ids: [] }
    },
  }
  const api = { classify: () => new Promise(() => {}), tasks: async () => [] }
  const app = renderer.createApp(Component, {
    monitor, api, canWrite: true, targetBatch: target,
    catalogue: [{ doc_type: 'DIPLOMA', label: '毕业证' }, { doc_type: 'MEDICAL_REPORT', label: '体检报告' }],
  })
  app.mount({})
  const exposed = app._instance.exposed
  exposed.personPackage.value = true
  const file = Object.assign(new File(['synthetic-account-A'], 'account-A.png'), { uid: 1 })
  exposed.fileList.value = [{ name: file.name, uid: 1, raw: file }]
  exposed.manualType(1, 'DIPLOMA')
  return { app, exposed, api, confirmations, submissions, file }
}

test('unmounted confirmation cannot upload old files after another account logs in', async () => {
  const h = harness()
  const pending = h.exposed.submit()
  assert.equal(h.confirmations.length, 1)
  h.app.unmount()
  h.confirmations[0]!.resolve('confirm')
  await pending
  assert.equal(h.submissions.length, 0)
})

test('client replacement during confirmation prevents submission without unmount', async () => {
  const h = harness()
  try {
    const pending = h.exposed.submit()
    h.app._instance.props.api = { ...h.api }
    h.confirmations[0]!.resolve('confirm')
    await pending
    assert.equal(h.submissions.length, 0)
    assert.equal(h.exposed.fileList.value.length, 1)
  } finally { h.app.unmount() }
})

test('confirmation locks reentry and normal append submits the captured types and revision once', async () => {
  const target = { batch_id: 'existing', package_revision: 3, person_name: 'Synthetic' }
  const h = harness(target)
  try {
    const pending = h.exposed.submit()
    assert.equal(h.exposed.submitting.value, true)
    await h.exposed.submit()
    assert.equal(h.confirmations.length, 1)
    h.confirmations[0]!.resolve('confirm')
    await pending
    assert.equal(h.submissions.length, 1)
    assert.deepEqual(h.submissions[0]!.options, { targetBatch: target, fileTypes: ['DIPLOMA'] })
    assert.equal(h.submissions[0]!.files[0], h.file)
    assert.equal(h.exposed.submitting.value, false)
    assert.equal(h.exposed.fileList.value.length, 0)
  } finally { h.app.unmount() }
})

test('cancelled confirmation retains files, releases the lock and permits a fresh confirmation', async () => {
  const h = harness()
  try {
    const pending = h.exposed.submit()
    h.confirmations[0]!.reject('cancel')
    await pending
    assert.equal(h.submissions.length, 0)
    assert.equal(h.exposed.fileList.value.length, 1)
    assert.equal(h.exposed.submitting.value, false)
    const retry = h.exposed.submit()
    h.confirmations[1]!.resolve('confirm')
    await retry
    assert.equal(h.submissions.length, 1)
  } finally { h.app.unmount() }
})

test('aborting the pending confirmation never starts an upload', async () => {
  const h = harness()
  try {
    const pending = h.exposed.submit()
    h.exposed.cancelSubmit()
    h.confirmations[0]!.resolve('confirm')
    await pending
    assert.equal(h.submissions.length, 0)
    assert.equal(h.exposed.submitting.value, false)
  } finally { h.app.unmount() }
})

test('changed package revision or selected type requires a fresh confirmation', async () => {
  for (const change of ['revision', 'type', 'file', 'permission']) {
    const h = harness({ batch_id: 'existing', package_revision: 3, person_name: 'Synthetic' })
    try {
      const pending = h.exposed.submit()
      if (change === 'revision') h.app._instance.props.targetBatch = { ...h.app._instance.props.targetBatch, package_revision: 4 }
      if (change === 'type') h.exposed.manualType(1, 'MEDICAL_REPORT')
      if (change === 'file') h.exposed.fileList.value = []
      if (change === 'permission') h.app._instance.props.canWrite = false
      h.confirmations[0]!.resolve('confirm')
      await pending
      assert.equal(h.submissions.length, 0, change)
    } finally { h.app.unmount() }
  }
})

test('single-type upload succeeds without a person confirmation', async () => {
  const h = harness()
  try {
    h.exposed.personPackage.value = false
    await h.exposed.submit()
    assert.equal(h.confirmations.length, 0)
    assert.equal(h.submissions.length, 1)
    assert.equal(h.submissions[0]!.type, 'MEDICAL_REPORT')
    assert.equal(h.submissions[0]!.options.fileTypes, undefined)
  } finally { h.app.unmount() }
})

test('busy or throttled uploads retain selected files and do not replay the submission', async () => {
  for (const [status, code] of [[503, 'SERVICE_BUSY'], [429, 'OPERATION_THROTTLED']] as const) {
    const h = harness()
    let calls = 0
    h.app._instance.props.monitor.submitUpload = async () => {
      calls++
      throw new ApiFailure(makeDiagnostic({ origin: 'http', operation: 'upload', code, status }), 2)
    }
    try {
      const pending = h.exposed.submit()
      h.confirmations[0]!.resolve('confirm')
      await pending
      await vue.nextTick()
      assert.equal(calls, 1)
      assert.equal(h.exposed.fileList.value.length, 1)
      assert.equal(h.exposed.fileList.value[0].raw, h.file)
      assert.equal(h.exposed.personPackage.value, true)
      assert.equal(h.exposed.submitting.value, false)
    } finally { h.app.unmount() }
  }
})

// f0804c0 完整性审计补测：银行卡复印件（BANK_CARD_COPY）与银行卡共用同一组上传门禁。
// 这些门禁此前按 BANK_CARD 硬编码，f0804c0 改为 isBankCardType 泛化后无任何测试钉住；
// 本组用例锁住泛化边界——既覆盖复印件，也不放宽非银行类型。
function bankFile(name: string) { return Object.assign(new File(['synthetic-copy'], name), { uid: 1 }) }

test('single-type bank photocopy rejects PDF at selection and shows the photo-only tip', async () => {
  const h = harness()
  try {
    h.exposed.personPackage.value = false
    h.exposed.fileList.value = [{ name: 'copy.pdf', uid: 1, raw: bankFile('copy.pdf') }]
    h.exposed.docType.value = 'BANK_CARD_COPY'
    assert.equal(h.exposed.photoOnly.value, true)
    assert.equal(h.exposed.invalidReason.value, '银行卡及复印件请上传单张 JPG/PNG/HEIC 照片，不接收 PDF。')
    h.exposed.docType.value = 'DIPLOMA'
    assert.equal(h.exposed.photoOnly.value, false)
    assert.equal(h.exposed.invalidReason.value, null)
  } finally { h.app.unmount() }
})

test('mixed packages name the bank-photocopy PDF offender at selection time', async () => {
  const h = harness()
  try {
    h.exposed.fileList.value = [{ name: '复印件.pdf', uid: 1, raw: bankFile('复印件.pdf') }]
    h.exposed.manualType(1, 'BANK_CARD_COPY')
    assert.equal(h.exposed.invalidReason.value, '「复印件.pdf」是 PDF：银行卡及复印件请上传单张 JPG/PNG/HEIC 照片，不接收 PDF。')
  } finally { h.app.unmount() }
})

test('submit refuses a bank-photocopy PDF even though the generic extension check accepts it', async () => {
  const h = harness()
  try {
    h.app._instance.props.catalogue = [{ doc_type: 'BANK_CARD_COPY', label: '银行卡复印件' }]
    h.exposed.personPackage.value = false
    h.exposed.fileList.value = [{ name: 'copy.pdf', uid: 1, raw: bankFile('copy.pdf') }]
    h.exposed.docType.value = 'BANK_CARD_COPY'
    await h.exposed.submit()
    assert.equal(h.submissions.length, 0)
    assert.equal(h.exposed.fileList.value.length, 1)
    assert.equal(h.confirmations.length, 0)
  } finally { h.app.unmount() }
})

test('a bank photocopy photo submits with its own type', async () => {
  const h = harness()
  try {
    h.app._instance.props.catalogue = [{ doc_type: 'BANK_CARD_COPY', label: '银行卡复印件' }]
    h.exposed.personPackage.value = false
    h.exposed.fileList.value = [{ name: 'copy.jpg', uid: 1, raw: bankFile('copy.jpg') }]
    h.exposed.docType.value = 'BANK_CARD_COPY'
    await h.exposed.submit()
    assert.equal(h.submissions.length, 1)
    assert.equal(h.submissions[0]!.type, 'BANK_CARD_COPY')
    assert.equal(h.submissions[0]!.options.fileTypes, undefined)
  } finally { h.app.unmount() }
})
