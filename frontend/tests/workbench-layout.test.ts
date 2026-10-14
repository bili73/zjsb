import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi, ApiFailure } from '../src/api.ts'
import { createWorkbenchLayout } from '../src/workbenchLayout.ts'
import type { WorkbenchLayout } from '../src/workbenchEntries.ts'
import type { DiagnosticCard } from '../src/diagnostics.ts'

const tick = () => new Promise(resolve => setTimeout(resolve, 0))
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
const error = (status: number) => new ApiFailure({ http_status: status } as DiagnosticCard)

test('default saves keep personal drafts and revisions; stale default writes require reload', async () => {
  let conflict = false, personal = 0
  const layout = createWorkbenchLayout(() => {})
  layout.bind({ workbenchLayout: async () => ({layout:['DIPLOMA'], revision:3, defaults:{layout:['TABLE'], revision:2}}),
    saveWorkbenchLayout: async () => { personal++; throw new Error('must not save personal draft') },
    saveWorkbenchDefault: async body => {
      assert.equal(body.expected_revision, conflict ? 3 : 2)
      if (conflict) throw error(409)
      return {layout:body.layout, revision:3}
    },
  })
  await tick()
  layout.state.editing = true; layout.state.layout = ['BANK_CARD']
  assert.equal(await layout.saveDefault(['BANK_CARD']), true)
  assert.deepEqual(layout.state.defaults, {layout:['BANK_CARD'], revision:3})
  assert.deepEqual(layout.state.layout, ['BANK_CARD'])
  assert.equal(layout.state.revision, 3)
  assert.equal(layout.state.editing, true)
  assert.equal(personal, 0)
  conflict = true
  assert.equal(await layout.saveDefault(null), false)
  assert.equal(layout.state.defaultConflict, true)
  assert.deepEqual(layout.state.layout, ['BANK_CARD'])
  await layout.load()
  assert.equal(layout.state.defaultConflict, false)
  assert.deepEqual(layout.state.defaults.layout, ['TABLE'])
})

function bind(layout: ReturnType<typeof createWorkbenchLayout>, client: {
  workbenchLayout: (signal: AbortSignal) => Promise<WorkbenchLayout>;
  saveWorkbenchLayout: (body: {layout: string[] | null; expected_revision: number}, signal: AbortSignal) => Promise<WorkbenchLayout>;
}) {
  layout.bind({
    workbenchLayout: async signal => ({ ...await client.workbenchLayout(signal), defaults: {layout:null, revision:0} }),
    saveWorkbenchLayout: async (body, signal) => ({ ...await client.saveWorkbenchLayout(body, signal), defaults: {layout:null, revision:0} }),
    saveWorkbenchDefault: async () => { throw new Error('unexpected default write') },
  })
}

test('layout API reads self and saves explicit revision using the existing session and CSRF', async () => {
  const calls: { url: string; init: RequestInit }[] = []
  const api = new BusinessApi((async (url, init) => {
    calls.push({ url: String(url), init: init! })
    return new Response(JSON.stringify(String(url).endsWith('/auth/me') ? {
      user_id: '11111111-2222-4333-8444-555555555555', display_name: 'User', role: 'operator',
      permissions: [], csrf_token: 'a'.repeat(64),
    } : { layout: [], revision: 1, defaults: {layout:null, revision:0} }))
  }) as typeof fetch)
  const signal = new AbortController().signal
  await api.auth(signal)
  await api.workbenchLayout(signal)
  await api.saveWorkbenchLayout({ layout: [], expected_revision: 0 }, signal)
  assert.equal(calls[1]!.url, '/api/v1/auth/me/workbench')
  assert.equal(calls[2]!.init.method, 'PUT')
  assert.equal(new Headers(calls[2]!.init.headers).get('X-CSRF-Token'), 'a'.repeat(64))
  assert.equal(calls[2]!.init.credentials, 'same-origin')
  assert.deepEqual(JSON.parse(String(calls[2]!.init.body)), { layout: [], expected_revision: 0 })
})

test('editing only changes a draft; explicit save commits and reload restores it', async () => {
  let saved: WorkbenchLayout = { layout: null, revision: 0 }, writes = 0
  const layout = createWorkbenchLayout(() => assert.fail('unexpected unauthorized'))
  bind(layout, { workbenchLayout: async () => saved, saveWorkbenchLayout: async body => {
    writes++; assert.equal(body.expected_revision, saved.revision)
    saved = { layout: body.layout, revision: saved.revision + 1 }; return saved
  } })
  await tick()
  layout.state.editing = true
  layout.state.layout = ['BANK_CARD', 'TABLE']
  assert.equal(writes, 0)
  assert.equal(await layout.save(), true)
  assert.equal(writes, 1)
  assert.equal(layout.state.editing, false)
  layout.state.editing = true
  layout.state.layout = null
  assert.equal(await layout.save(), true)
  await layout.load()
  assert.equal(layout.state.revision, 2)
  assert.equal(layout.state.layout, null)
})

test('failed saves and conflicts preserve draft and original revision until explicit reload', async () => {
  let status = 500, calls = 0
  const layout = createWorkbenchLayout(() => {})
  bind(layout, { workbenchLayout: async () => ({ layout: ['TABLE'], revision: 4 }),
    saveWorkbenchLayout: async () => { calls++; throw error(status) } })
  await tick()
  layout.state.editing = true; layout.state.layout = []
  assert.equal(await layout.save(), false)
  assert.deepEqual(layout.state.layout, [])
  assert.equal(layout.state.revision, 4)
  assert.equal(layout.state.editing, true)
  status = 409
  await layout.save()
  assert.equal(layout.state.conflict, true)
  await layout.save()
  assert.equal(calls, 2)
  assert.deepEqual(layout.state.layout, [])
  await layout.load()
  assert.equal(layout.state.conflict, false)
  assert.deepEqual(layout.state.layout, ['TABLE'])
})

test('failed initial read cannot turn defaults into a write', async () => {
  const layout = createWorkbenchLayout(() => {})
  bind(layout, { workbenchLayout: async () => { throw error(500) }, saveWorkbenchLayout: async () => { throw new Error('must not write') } })
  await tick()
  layout.state.editing = true
  assert.equal(await layout.save(), false)
  assert.equal(layout.state.loaded, false)
  assert.ok(layout.state.error)
})

test('account changes fence late reads and saves even when transport ignores abort', async () => {
  for (const pendingKind of ['read', 'save']) {
    const old = deferred<WorkbenchLayout>()
    let oldSignal: AbortSignal | undefined
    const layout = createWorkbenchLayout(() => {})
    bind(layout, { workbenchLayout: async signal => {
      oldSignal = signal
      return pendingKind === 'read' ? old.promise : { layout: ['TABLE'], revision: 1 }
    }, saveWorkbenchLayout: async (_, signal) => { oldSignal = signal; return old.promise } })
    await tick()
    if (pendingKind === 'save') { layout.state.editing = true; void layout.save() }
    bind(layout, { workbenchLayout: async () => ({ layout: ['BANK_CARD'], revision: 3 }),
      saveWorkbenchLayout: async () => { throw new Error('unexpected save') } })
    assert.equal(oldSignal?.aborted, true)
    await tick()
    old.resolve({ layout: ['DIPLOMA'], revision: 99 })
    await tick()
    assert.deepEqual(layout.state.layout, ['BANK_CARD'])
    assert.equal(layout.state.revision, 3)
    assert.equal(layout.state.editing, false)
    layout.dispose()
    assert.equal(layout.state.layout, null)
  }
})

test('expired sessions notify the owner and double-clicks do not duplicate writes', async () => {
  let unauthorized = 0, writes = 0
  const pending = deferred<WorkbenchLayout>()
  const layout = createWorkbenchLayout(() => { unauthorized++ })
  bind(layout, { workbenchLayout: async () => { throw error(401) }, saveWorkbenchLayout: async () => pending.promise })
  await tick()
  assert.equal(unauthorized, 1)
  bind(layout, { workbenchLayout: async () => ({ layout: null, revision: 0 }), saveWorkbenchLayout: async () => { writes++; return pending.promise } })
  await tick()
  layout.state.editing = true
  const first = layout.save()
  assert.equal(await layout.save(), false)
  assert.equal(writes, 1)
  pending.resolve({ layout: [], revision: 1 })
  assert.equal(await first, true)
})
