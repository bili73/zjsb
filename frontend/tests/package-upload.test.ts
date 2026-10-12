import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { parseClassification } from '../src/business.ts'
import type { Classification } from '../src/business.ts'
import { createClassificationQueue } from '../src/packageUpload.ts'

const result: Classification = { doc_type: 'DIPLOMA', basis: 'content', reason: '核对类型', candidates: ['DIPLOMA'] }
const tick = () => new Promise(resolve => setTimeout(resolve, 0))

test('classification decoder rejects invalid routing and inconsistent suggestions', () => {
  assert.deepEqual(parseClassification(result), result)
  assert.equal(parseClassification({ ...result, doc_type: null, basis: 'unknown', candidates: [] }).doc_type, null)
  for (const invalid of [{ doc_type: 'made-up' }, { basis: 'model' }, { doc_type: null }, { candidates: [] }, { candidates: ['made-up'] }, { reason: 'x'.repeat(201) }]) {
    assert.throws(() => parseClassification({ ...result, ...invalid }))
  }
})

test('mixed multipart binds types by file order including repeated filenames', async () => {
  const seen: { path: string; form: FormData }[] = []
  const batchId = crypto.randomUUID()
  const api = new BusinessApi(async (path, init) => {
    seen.push({ path: String(path), form: init!.body as FormData })
    return new Response(JSON.stringify(String(path).endsWith('/classify') ? result : { batch_id: batchId, task_ids: [] }))
  })
  const files = [new File(['first'], 'same.png'), new File(['second'], 'same.png')]
  const signal = new AbortController().signal
  const kinds = ['DIPLOMA', 'MEDICAL_REPORT'] as const
  await api.upload(files, 'DIPLOMA', true, signal, 'Synthetic Person', kinds)
  await api.append({ batch_id: batchId, status: 'PROCESSING', package_revision: 2 }, files, 'DIPLOMA', true, signal, kinds)
  await api.classify(files[0]!, signal)
  for (const upload of seen.slice(0, 2)) {
    assert.deepEqual(JSON.parse(String(upload.form.get('file_types'))), kinds)
    assert.equal(upload.form.get('doc_type_hint'), null)
    assert.equal(upload.form.get('abnormal_only'), 'true')
    assert.deepEqual(await Promise.all((upload.form.getAll('files') as File[]).map(file => file.text())), ['first', 'second'])
  }
  assert.equal(seen[0]!.form.get('person_name'), 'Synthetic Person')
  assert.equal(seen[1]!.form.get('person_name'), null)
  assert.equal(seen[1]!.form.get('expected_revision'), '2')
  assert.equal(seen[2]!.form.getAll('files').length, 1)
  assert.equal(seen[2]!.form.get('file_types'), null)
})

test('classification is serial and a manual override invalidates the late answer', async () => {
  const first = Promise.withResolvers<Classification>()
  const started: string[] = [], updates: number[] = []
  let active = 0, maxActive = 0
  const queue = createClassificationQueue(async file => {
    started.push(file.name); active++; maxActive = Math.max(active, maxActive)
    const response = file.name === 'first' ? await first.promise : result
    active--; return response
  }, (uid, value) => { if (value) updates.push(uid) })
  queue.add(1, new File(['first'], 'first'))
  queue.add(2, new File(['second'], 'second'))
  assert.deepEqual(started, ['first'])
  queue.remove(1) // The user chose a type while its request was running.
  first.resolve(result)
  await tick()
  assert.deepEqual(updates, [2])
  assert.equal(maxActive, 1)
  queue.dispose()
})

test('removed/unmounted pending responses cannot repopulate rows; failures allow next file', async () => {
  const first = Promise.withResolvers<Classification>()
  const updates: number[] = [], failures: unknown[] = []
  const queue = createClassificationQueue(async file => {
    if (file.name === 'bad') throw new Error('synthetic unavailable')
    return first.promise
  }, (uid, value) => { if (value) updates.push(uid) }, error => failures.push(error))
  queue.add(1, new File(['bad'], 'bad'))
  queue.add(2, new File(['late'], 'late'))
  await tick()
  assert.equal(failures.length, 1)
  queue.dispose()
  first.resolve(result)
  await tick()
  assert.deepEqual(updates, [])
})
