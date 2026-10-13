import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { ApiFailure } from '../src/api.ts'
import type { Batch } from '../src/business.ts'

// Exercise the actual component's edit/save functions and reactive prop changes.
const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc'), ts = require('typescript')
const vue = await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath = fileURLToPath(new URL('../src/components/PersonNameEditor.vue', import.meta.url))
const source = (await readFile(sourcePath, 'utf8')).replace('</script>',
  'defineExpose({ edit, save, editing, name, message })\n</script>')
const compiled = compileScript(parse(source, { filename: sourcePath }).descriptor, { id: 'person-name-test' })
const dataUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const elementStub = dataUrl('export const ElMessage = { success(){} };')
const code = ts.transpileModule(compiled.content, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]([^'"]+)['"]/g, (_: string, specifier: string) => {
  const resolved = specifier.startsWith('.') ? path.resolve(path.dirname(sourcePath), specifier) : require.resolve(specifier)
  return `from '${specifier === 'element-plus' ? elementStub : pathToFileURL(resolved).href}'`
})
const Component = (await import(dataUrl(code))).default
Component.render = () => null
const renderer = vue.createRenderer({
  patchProp() {}, insert() {}, remove() {}, createElement() { return {} }, createText() { return {} },
  createComment() { return {} }, setText() {}, setElementText() {}, parentNode() { return null }, nextSibling() { return null },
})

function mount() {
  const current = { batch_id: 'synthetic', status: 'COMPLETED', package_revision: 1, person_name: 'Initial' } as Batch
  const saved: Batch[] = []
  let refreshes = 0
  const app = renderer.createApp(Component, { batch: { ...current }, canWrite: true, monitor: {
    start() { refreshes++ },
    async confirmPerson(snapshot: Batch, name: string) {
      saved.push({ ...snapshot })
      if (snapshot.package_revision !== current.package_revision) {
        throw new ApiFailure({ http_status: 409, code: 'RESULT_VERSION_CONFLICT' } as ApiFailure['card'])
      }
      current.person_name = name
      current.package_revision!++
    },
  } })
  app.mount({})
  return { app, current, saved, exposed: app._instance.exposed, props: app._instance.props, refreshes: () => refreshes }
}

for (const change of ['replace', 'mutate']) {
  test(`old name draft keeps its edit revision when props ${change}, and conflict preserves the draft`, async () => {
    const h = mount()
    try {
      h.exposed.edit('My old draft')
      h.current.package_revision = 2; h.current.person_name = 'Other administrator'
      if (change === 'replace') h.props.batch = { ...h.current }
      else Object.assign(h.props.batch, h.current)
      await h.exposed.save()
      assert.equal(h.saved[0]!.package_revision, 1)
      assert.equal(h.current.person_name, 'Other administrator')
      assert.equal(h.exposed.name.value, 'My old draft')
      assert.equal(h.exposed.editing.value, true)
      assert.match(h.exposed.message.value, /材料包已更新/)
      assert.equal(h.refreshes(), 1)
      h.exposed.editing.value = false // The existing cancel button.
      h.exposed.edit()
      assert.equal(h.exposed.name.value, 'Other administrator')
      h.exposed.name.value = 'Reviewed latest information'
      await h.exposed.save()
      assert.equal(h.saved[1]!.package_revision, 2)
      assert.equal(h.current.person_name, 'Reviewed latest information')
      assert.equal(h.exposed.editing.value, false)
    } finally { h.app.unmount() }
  })
}

test('normal name save remains valid after unrelated task metadata refresh', async () => {
  const h = mount()
  try {
    h.exposed.edit('  Reviewed name  ')
    h.props.batch = { ...h.current, completed_count: 3 }
    await h.exposed.save()
    assert.equal(h.current.person_name, 'Reviewed name')
    assert.equal(h.current.package_revision, 2)
    assert.equal(h.exposed.editing.value, false)
    assert.equal(h.refreshes(), 0)
  } finally { h.app.unmount() }
})
