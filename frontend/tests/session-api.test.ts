import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi } from '../src/api.ts'
import { parseUser } from '../src/business.ts'
const csrf='a'.repeat(64)
const user={user_id:'11111111-2222-4333-8444-555555555555',display_name:'合成用户',role:'operator',permissions:['review'],csrf_token:csrf}

test('login/restoration use cookies; writes send only the in-memory CSRF header',async()=>{
  const calls:{url:string;init:RequestInit}[]=[]
  const api=new BusinessApi((async(url,init)=>{
    calls.push({url:String(url),init:init??{}})
    if(String(url).endsWith('/logout'))return new Response(null,{status:204})
    return new Response(JSON.stringify(user),{headers:{'Content-Type':'application/json'}})
  }) as typeof fetch)
  const signal=new AbortController().signal
  assert.equal((await api.login('tester','synthetic password',signal)).display_name,user.display_name)
  assert.equal(JSON.parse(String(calls[0]?.init.body)).password,'synthetic password')
  assert.equal(new Headers(calls[0]?.init.headers).get('X-CSRF-Token'),null)
  await api.auth(signal)
  assert.equal(new Headers(calls[1]?.init.headers).get('X-CSRF-Token'),null)
  await api.logout(signal)
  assert.equal(new Headers(calls[2]?.init.headers).get('X-CSRF-Token'),csrf)
  for(const c of calls){assert.equal(c.init.credentials,'same-origin');assert.equal(new Headers(c.init.headers).get('X-API-Key'),null);assert.ok(!c.url.includes('synthetic'))}
})

test('CSRF tokens must have the response contract shape',()=>{
  assert.equal(parseUser(user).csrf_token,csrf)
  for(const value of [null,123,'bad',{},'b'.repeat(65)]) assert.throws(()=>parseUser({...user,csrf_token:value}))
})
