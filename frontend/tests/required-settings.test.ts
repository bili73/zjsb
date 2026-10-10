import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi, ApiFailure } from '../src/api.ts'
import { parseRequiredFieldSettings, selectedRequiredFields, memberFieldRequired } from '../src/requiredFields.ts'
import { parseTask, resultKey, requiredFieldLabels } from '../src/business.ts'
import type { TaskResult } from '../src/business.ts'

const settings = () => ({ revision: 0, items: [{ doc_type: 'DIPLOMA', label: '毕业证', uses_defaults: true, fields: [
  { key: 'name', label: '姓名', required: true, editable: true, type: 'string' },
  { key: 'duration', label: '学制', required: false, editable: true, type: 'string' },
] }] })
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('settings decoder rejects invalid policy and derived required fields', () => {
  assert.deepEqual(selectedRequiredFields(parseRequiredFieldSettings(settings()).items[0]!), ['name'])
  for (const value of [-1, 1.2, true, '1']) assert.throws(() => parseRequiredFieldSettings({ ...settings(), revision: value }))
  const derived = settings()
  derived.items[0]!.fields[0]!.editable = false
  assert.throws(() => parseRequiredFieldSettings(derived))
  const duplicate = settings()
  duplicate.items.push(duplicate.items[0]!)
  assert.throws(() => parseRequiredFieldSettings(duplicate))
})

test('configuration API uses CSRF, global revision and null for restore', async () => {
  const saved: unknown[] = []
  const api = new BusinessApi(async (url, init) => {
    if (String(url).endsWith('/auth/me')) return json({ user_id: crypto.randomUUID(), display_name: '合成管理员', role: 'admin', permissions: [], csrf_token: 'a'.repeat(64) })
    if (init?.method === 'PUT') {
      assert.equal(new Headers(init.headers).get('X-CSRF-Token'), 'a'.repeat(64))
      assert.equal(init.credentials, 'same-origin')
      saved.push(JSON.parse(String(init.body)))
    }
    return json(settings())
  })
  const signal = new AbortController().signal
  await api.auth(signal)
  assert.equal((await api.requiredFields(signal)).revision, 0)
  await api.saveRequiredFields({ doc_type: 'DIPLOMA', required_fields: [], expected_revision: 0 }, signal)
  await api.saveRequiredFields({ doc_type: 'DIPLOMA', required_fields: null, expected_revision: 0 }, signal)
  assert.deepEqual(saved, [{ doc_type: 'DIPLOMA', required_fields: [], expected_revision: 0 }, { doc_type: 'DIPLOMA', required_fields: null, expected_revision: 0 }])
})

test('stale settings are an explicit conflict and never retried as a save', async () => {
  let calls = 0
  const api = new BusinessApi(async () => { calls++; return json({ code: 'SETTINGS_VERSION_CONFLICT' }, 409) })
  await assert.rejects(api.saveRequiredFields({ doc_type: 'DIPLOMA', required_fields: ['name'], expected_revision: 0 }, new AbortController().signal), error =>
    error instanceof ApiFailure && error.card.code === 'SETTINGS_VERSION_CONFLICT' && error.card.http_status === 409)
  assert.equal(calls, 1)
})

test('policy revision invalidates result identity without inventing a task revision', () => {
  const task = { task_id: crypto.randomUUID(), run_id: crypto.randomUUID(), result_revision: 1, cancel_requested: false, status: 'NEED_REVIEW', page_count: 0, pages: [] }
  const before = parseTask({ ...task, required_fields_revision: 0 })
  const after = parseTask({ ...task, required_fields_revision: 1 })
  assert.notEqual(resultKey(before), resultKey(after))
  assert.equal(before.result_revision, after.result_revision)
  assert.throws(() => parseTask({ ...task, required_fields_revision: -1 }))
  assert.equal(resultKey(parseTask(task)), `${task.task_id}:${task.run_id}:1`)
})

test('configured member keys drive editing requirements and Chinese missing labels', () => {
  const result = { required_field_keys: ['members.occupation'] } as TaskResult
  assert.equal(memberFieldRequired(result, 'name'), false)
  assert.equal(memberFieldRequired(result, 'occupation'), true)
  assert.equal(memberFieldRequired({} as TaskResult, 'name'), true)
  assert.deepEqual(requiredFieldLabels({ status: 'NEED_REVIEW', doc_type: 'HOUSEHOLD_REGISTER', export_ready: false,
    export_blockers: [{ field: 'members[0].occupation', code: 'MISSING' }] }, []), ['成员 1 / 职业'])
})
