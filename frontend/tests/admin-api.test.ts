import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi, ApiFailure } from '../src/api.ts'
import { parseManagedUsers } from '../src/business.ts'
import { diagnosticCards } from '../src/diagnostics.ts'

const user = { user_id: '11111111-2222-4333-8444-555555555555', username: 'tester', display_name: '合成用户', role: 'operator', enabled: true }
const csrf = 'a'.repeat(64)

test('editing account name sends only display_name with session CSRF and validates returned account', async () => {
  let sent: RequestInit | undefined
  const api = new BusinessApi(async (path, init) => {
    if (String(path).endsWith('/auth/me')) return Response.json({ user_id: user.user_id, display_name: '管理员', role: 'admin', permissions: [], csrf_token: csrf })
    assert.equal(String(path), '/api/v1/admin/users/' + user.user_id)
    sent = init
    return Response.json({ ...user, display_name: '修改姓名' })
  })
  const signal = new AbortController().signal
  await api.auth(signal)
  assert.equal((await api.updateUserName(user.user_id, '修改姓名', signal)).display_name, '修改姓名')
  assert.equal(sent?.method, 'PATCH')
  assert.deepEqual(JSON.parse(String(sent?.body)), { display_name: '修改姓名' })
  assert.equal(new Headers(sent?.headers).get('X-CSRF-Token'), csrf)
  assert.equal(sent?.credentials, 'same-origin')
})

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

test('account mutations send minimal bodies with CSRF and accept empty 204 responses', async () => {
  const calls: { path: string; init: RequestInit }[] = []
  const api = new BusinessApi((async (path, init) => {
    calls.push({ path: String(path), init: init ?? {} })
    if (String(path).endsWith('/auth/me')) return Response.json({ user_id: user.user_id, display_name: '管理员', role: 'admin', permissions: [], csrf_token: csrf })
    if (init?.method === 'PATCH') return Response.json({ ...user, enabled: false })
    return new Response(null, { status: 204 })
  }) as typeof fetch)
  const signal = new AbortController().signal
  await api.auth(signal)
  assert.equal((await api.updateUserEnabled(user.user_id, false, signal)).enabled, false)
  assert.equal(await api.resetUserPassword(user.user_id, 'synthetic new password', signal), undefined)
  assert.equal(await api.deleteUser(user.user_id, signal), undefined)
  assert.equal(await api.changePassword('synthetic old password', 'synthetic new password', signal), undefined)
  assert.deepEqual(calls.slice(1).map(call => [call.path, call.init.method, call.init.body ? JSON.parse(String(call.init.body)) : null]), [
    [`/api/v1/admin/users/${user.user_id}`, 'PATCH', { enabled: false }],
    [`/api/v1/admin/users/${user.user_id}/password`, 'POST', { new_password: 'synthetic new password' }],
    [`/api/v1/admin/users/${user.user_id}`, 'DELETE', null],
    ['/api/v1/auth/password', 'POST', { current_password: 'synthetic old password', new_password: 'synthetic new password' }],
  ])
  for (const call of calls.slice(1)) {
    assert.equal(call.init.credentials, 'same-origin')
    assert.equal(new Headers(call.init.headers).get('X-CSRF-Token'), csrf)
  }
  await api.logout(signal)
  assert.equal(new Headers(calls.at(-1)?.init.headers).get('X-CSRF-Token'), null)
})

test('incorrect current password stays a retryable form error and diagnostics exclude secrets', async () => {
  diagnosticCards.value = []
  const api = new BusinessApi((async () => Response.json({ code: 'CURRENT_PASSWORD_INCORRECT', message: 'synthetic secret body' }, { status: 422 })) as typeof fetch)
  await assert.rejects(api.changePassword('synthetic old password', 'synthetic new password', new AbortController().signal),
    (error: unknown) => error instanceof ApiFailure && error.card.code === 'CURRENT_PASSWORD_INCORRECT' && error.card.http_status === 422)
  assert.equal(diagnosticCards.value[0]?.operation, 'password_change')
  assert.equal(JSON.stringify(diagnosticCards.value).includes('synthetic'), false)
  const protectedApi = new BusinessApi((async () => Response.json({ code: 'ACCOUNT_PROTECTED' }, { status: 409 })) as typeof fetch)
  await assert.rejects(protectedApi.deleteUser(user.user_id, new AbortController().signal),
    (error: unknown) => error instanceof ApiFailure && error.card.code === 'ACCOUNT_PROTECTED')
})
