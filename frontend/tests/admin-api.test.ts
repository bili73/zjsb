import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi, ApiFailure } from '../src/api.ts'
import { parseManagedUsers } from '../src/business.ts'

const user = { user_id: '11111111-2222-4333-8444-555555555555', username: 'tester', display_name: '合成用户', role: 'operator', enabled: true }
const csrf = 'a'.repeat(64)

test('administrator creation keeps Cookie CSRF and returns only public account fields', async () => {
  const calls: { path: string; init: RequestInit }[] = []
  const api = new BusinessApi((async (path, init) => {
    calls.push({ path: String(path), init: init ?? {} })
    if (String(path).endsWith('/auth/me')) return Response.json({ user_id: user.user_id, display_name: '管理员', role: 'admin', permissions: [], csrf_token: csrf })
    return Response.json(init?.method === 'POST' ? user : { items: [user] }, { status: init?.method === 'POST' ? 201 : 200 })
  }) as typeof fetch)
  const signal = new AbortController().signal
  await api.auth(signal)
  assert.deepEqual(await api.users(signal), [user])
  assert.deepEqual(await api.createUser({ username: 'tester', display_name: '合成用户', password: 'test1234', role: 'operator' }, signal), user)
  assert.equal(calls[2]?.path, '/api/v1/admin/users')
  assert.equal(calls[2]?.init.credentials, 'same-origin')
  assert.equal(new Headers(calls[2]?.init.headers).get('X-CSRF-Token'), csrf)
  assert.equal(new Headers(calls[1]?.init.headers).get('X-CSRF-Token'), null)
})

test('duplicate account error stays explicit and unexpected credential fields are rejected', async () => {
  const api = new BusinessApi((async () => Response.json({ code: 'USERNAME_EXISTS' }, { status: 409 })) as typeof fetch)
  await assert.rejects(api.createUser({ username: 'tester', display_name: '合成用户', password: 'test1234', role: 'operator' }, new AbortController().signal),
    (error: unknown) => error instanceof ApiFailure && error.card.code === 'USERNAME_EXISTS')
  assert.throws(() => parseManagedUsers({ items: [{ ...user, password_hash: 'must not arrive' }] }))
  assert.throws(() => parseManagedUsers({ items: [{ ...user, role: 'owner' }] }))
})
