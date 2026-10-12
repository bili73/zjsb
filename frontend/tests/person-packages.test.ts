import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { isPersonPackage, pairingLabels, parseBatches, sampleQualification } from '../src/business.ts'
import { spreadsheetName } from '../src/review.ts'
import type { Batch } from '../src/business.ts'
import { createMonitor } from '../src/monitor.ts'

const batch: Batch = { batch_id: crypto.randomUUID(), status: 'PROCESSING', person_name: 'Synthetic Person', package_revision: 2, id_card_pairing: 'missing_back' }
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })

test('person package decoder rejects ambiguous assignment and malformed pairing metadata', () => {
  const list = (item: unknown) => ({ items: [item], total: 1, page: 1, page_size: 50 })
  assert.equal(parseBatches(list(batch)).items[0]!.person_name, batch.person_name)
  for (const invalid of [{ person_name: '' }, { person_name: null }, { package_revision: -1 },
    { id_card_pairing: 'paired' }, { id_card_pairing: 'unassigned' }, { expires_at: 'tomorrow' }, { warnings: [{ code: 'MISSING_ID_BACK' }] }]) {
    assert.throws(() => parseBatches(list({ ...batch, ...invalid })))
  }
  assert.equal(parseBatches(list({ batch_id: batch.batch_id, status: 'COMPLETED' })).items.length, 1)
})

test('creation and append transmit explicit person or immutable package version with one type', async () => {
  const seen: { path: string; form: FormData }[] = []
  const client = new BusinessApi(async (input, init) => {
    seen.push({ path: String(input), form: init!.body as FormData })
    return json({ batch_id: batch.batch_id, task_ids: [] })
  })
  const file = new File(['synthetic'], 'synthetic.png', { type: 'image/png' })
  const signal = new AbortController().signal
  await client.upload([file], 'ID_CARD_FRONT', false, signal, batch.person_name!)
  await client.append(batch, [file], 'ID_CARD_BACK', false, signal)
  assert.equal(seen[0]!.form.get('person_name'), batch.person_name)
  assert.equal(seen[1]!.path, `/api/v1/batches/${batch.batch_id}/append`)
  assert.equal(seen[1]!.form.get('expected_revision'), '2')
  assert.equal(seen[1]!.form.get('doc_type_hint'), 'ID_CARD_BACK')
  assert.equal(seen[1]!.form.get('person_name'), null)
  assert.equal(seen[1]!.form.getAll('files').length, 1)
})

test('late append response cannot restore a package after account switching', async () => {
  const entered = Promise.withResolvers<void>(), response = Promise.withResolvers<Response>()
  let current = new BusinessApi(async () => { entered.resolve(); return response.promise })
  const monitor = createMonitor(() => current, { isVisible: () => false })
  try {
    const pending = monitor.submitUpload([new File(['synthetic'], 'synthetic.png')], 'ID_CARD_BACK', false,
      new AbortController().signal, { targetBatch: batch })
    await entered.promise
    monitor.clear()
    current = new BusinessApi(async () => json({ items: [], total: 0, page: 1, page_size: 50 }))
    response.resolve(json({ batch_id: batch.batch_id, task_ids: [crypto.randomUUID()] }))
    await pending
    assert.deepEqual(monitor.state.entries, {})
    assert.equal(monitor.state.polling, false)
  } finally { monitor.dispose() }
})

test('missing-sample types remain explicitly unqualified', () => {
  assert.match(sampleQualification('ID_CARD_FRONT'), /尚缺真实样本/)
  assert.match(sampleQualification('PASSPORT'), /尚缺真实样本/)
  assert.match(sampleQualification('BANK_CARD'), /有限真实样本/)
})

test('front-only package describes the back as optional', () => {
  assert.match(pairingLabels.missing_back, /可选，可仅识别人像面/)
  assert.doesNotMatch(pairingLabels.missing_back, /缺少|必须/)
})

test('pending packages decode candidates with source task identities and remain packages', () => {
  const candidate = { name: '合成姓名', sources: [{ task_id: crypto.randomUUID(), doc_type: 'DIPLOMA', file_name: 'synthetic.png' }] }
  const pending = { ...batch, person_name: null, is_person_package: true, name_suggestions: [candidate] }
  const list = (item: unknown) => ({ items: [item], total: 1, page: 1, page_size: 50 })
  assert.equal(isPersonPackage(parseBatches(list(pending)).items[0]!), true)
  for (const invalid of [{ is_person_package: 'true' }, { name_suggestions: [{ ...candidate, name: '' }] },
    { name_suggestions: [{ ...candidate, sources: [] }] }, { name_suggestions: [{ ...candidate, sources: [{ task_id: 'not-uuid' }] }] }]) {
    assert.throws(() => parseBatches(list({ ...pending, ...invalid })))
  }
})

test('mixed upload omits name and name confirmation sends shared revision', async () => {
  const seen: { path: string; init: RequestInit }[] = []
  const updated = { ...batch, is_person_package: true, person_name: '确认姓名', package_revision: 3 }
  const client = new BusinessApi(async (input, init) => {
    seen.push({ path: String(input), init: init! })
    return json(init!.method === 'PATCH' ? updated : { batch_id: batch.batch_id, task_ids: [] })
  })
  const signal = new AbortController().signal
  await client.upload([new File(['synthetic'], 'a.png')], 'DIPLOMA', false, signal, undefined, ['DIPLOMA'])
  assert.equal((seen[0]!.init.body as FormData).get('person_name'), null)
  assert.equal((await client.confirmPerson(batch, '确认姓名', signal)).package_revision, 3)
  assert.equal(seen[1]!.init.method, 'PATCH')
  assert.equal(seen[1]!.path, `/api/v1/batches/${batch.batch_id}/person`)
  assert.deepEqual(JSON.parse(seen[1]!.init.body as string), { person_name: '确认姓名', expected_revision: 2 })
})

test('late name confirmation cannot restore another account package', async () => {
  const response = Promise.withResolvers<Response>()
  let current = new BusinessApi(async () => response.promise)
  const monitor = createMonitor(() => current, { isVisible: () => false })
  try {
    const pending = monitor.confirmPerson(batch, '确认姓名', new AbortController().signal)
    monitor.clear()
    current = new BusinessApi(async () => json({ items: [], total: 0, page: 1, page_size: 50 }))
    response.resolve(json({ ...batch, person_name: '确认姓名', package_revision: 3 }))
    await pending
    assert.deepEqual(monitor.state.entries, {})
  } finally { monitor.dispose() }
})

test('package workbook filename uses Shanghai time and stable package label', () => {
  assert.equal(spreadsheetName(['DIPLOMA'], new Date('2026-10-12T01:02:03Z'), true), '人员材料包_20261012_090203.xlsx')
  assert.equal(spreadsheetName(['DIPLOMA'], new Date('2026-10-12T01:02:03Z')), '毕业证_20261012_090203.xlsx')
})

test('older-page package metadata refreshes after append and after saved field corrections', async () => {
  const id = crypto.randomUUID(), tid = crypto.randomUUID()
  const before: Batch = { batch_id: id, status: 'PROCESSING', person_name: null, is_person_package: true,
    package_revision: 0, id_card_pairing: 'not_provided', name_suggestions: [] }
  const task = { task_id: tid, batch_id: id, run_id: crypto.randomUUID(), result_revision: 0,
    cancel_requested: false, status: 'NEED_REVIEW', page_count: 1, pages: [], doc_type: 'DIPLOMA' }
  let fresh: Batch = before, visible = true
  const client = new BusinessApi(async input => {
    const url = String(input)
    if (url.includes('/batches?')) return json({ items: url.includes('page=2') ? [fresh] : [], total: 1, page: url.includes('page=2') ? 2 : 1, page_size: 50 })
    if (url.endsWith('/tasks')) return json([task])
    if (url.endsWith(`/batches/${id}`)) return json(fresh)
    if (url.endsWith('/append')) { fresh = { ...fresh, package_revision: 1, name_suggestions: [{ name: '合成姓名', sources: [{ task_id: tid, doc_type: 'DIPLOMA', file_name: 'synthetic.png' }] }] }; return json({ batch_id: id, task_ids: [] }) }
    throw new Error('UNEXPECTED_TEST_PATH')
  })
  const monitor = createMonitor(() => client, { isVisible: () => visible })
  const signal = new AbortController().signal
  try {
    await monitor.pollOnce(signal); await monitor.loadMore(signal); await monitor.loadTasks(id, signal)
    visible = false
    await monitor.submitUpload([new File(['synthetic'], 'a.png')], 'DIPLOMA', false, signal, { targetBatch: before })
    visible = true
    await monitor.pollOnce(signal)
    assert.equal(monitor.state.entries[id]!.batch!.package_revision, 1)
    assert.equal(monitor.state.entries[id]!.batch!.name_suggestions![0]!.name, '合成姓名')
    assert.equal(await monitor.pollOnce(signal), null)
    fresh = { ...fresh, name_suggestions: [{ name: '保存后姓名', sources: [{ task_id: tid, doc_type: 'DIPLOMA', file_name: 'synthetic.png' }] }] }
    task.result_revision++
    await monitor.pollOnce(signal, true)
    assert.equal(monitor.state.entries[id]!.batch!.name_suggestions![0]!.name, '保存后姓名')
  } finally { monitor.dispose() }
})

test('recognition finishing between list and task reads still supplies name suggestions', async () => {
  const id = crypto.randomUUID(), tid = crypto.randomUUID()
  const initial: Batch = { batch_id: id, status: 'PROCESSING', is_person_package: true, person_name: null,
    package_revision: 0, id_card_pairing: 'not_provided', name_suggestions: [] }
  const finished: Batch = { ...initial, name_suggestions: [{ name: '完成姓名', sources: [{ task_id: tid, doc_type: 'DIPLOMA', file_name: 'synthetic.png' }] }] }
  const client = new BusinessApi(async input => {
    const url = String(input)
    if (url.includes('/batches?')) return json({ items: [initial], total: 1, page: 1, page_size: 50 })
    if (url.endsWith('/tasks')) return json([{ task_id: tid, batch_id: id, run_id: crypto.randomUUID(), result_revision: 1,
      cancel_requested: false, status: 'NEED_REVIEW', page_count: 1, pages: [], doc_type: 'DIPLOMA' }])
    if (url.endsWith(`/batches/${id}`)) return json(finished)
    throw new Error('UNEXPECTED_TEST_PATH')
  })
  const monitor = createMonitor(() => client, { isVisible: () => true })
  try {
    await monitor.pollOnce(new AbortController().signal)
    assert.equal(monitor.state.entries[id]!.batch!.name_suggestions![0]!.name, '完成姓名')
  } finally { monitor.dispose() }
})
