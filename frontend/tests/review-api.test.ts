import test from 'node:test'
import assert from 'node:assert/strict'
import { BusinessApi, ApiFailure } from '../src/api.ts'
import { parseCatalogue, parseResult } from '../src/business.ts'
import type { Task } from '../src/business.ts'
const id = '11111111-2222-4333-8444-555555555555'
const task = { task_id: id, run_id:id, result_revision:3 } as Task
test('catalogue rejects retired frontend aliases', () => {
  assert.equal(parseCatalogue([{doc_type:'ID_CARD_BACK',label:'国徽面',fields:[]}]).length,1)
  assert.throws(()=>parseCatalogue([{doc_type:'ID_CARD',label:'身份证',fields:[]}]))
})
test('preview authenticates with the browser session and verifies corrected stage and exact revision', async () => {
  let path='', init:RequestInit|undefined
  const api=new BusinessApi( (async (input,options)=> {path=String(input);init=options; return new Response(new Blob(['pixels'],{type:'image/png'}),{headers:{'Content-Type':'image/png','X-Preview-Stage':'corrected','X-Result-Revision':'3'}})}) as typeof fetch)
  const result=await api.preview(task,2,new AbortController().signal)
  assert.equal(result.corrected,true)
  assert.match(path,/run_id=/);assert.match(path,/result_revision=3/);assert.match(path,/page=2/)
  assert.equal(new Headers(init?.headers).get('X-API-Key'),null)
  assert.equal(init?.credentials,'same-origin')
  assert.ok(!path.includes('test-only'))
  await api.preview(task,2,new AbortController().signal,'人工核对')
  assert.equal(init?.method,'POST')
  assert.equal(JSON.parse(String(init?.body)).expected_revision,3)
})
test('preview without trusted transform headers has no overlay permission', async()=>{
  const api=new BusinessApi( (async()=>new Response(new Blob(['pixels'],{type:'image/png'}),{headers:{'Content-Type':'image/png'}})) as typeof fetch)
  assert.equal((await api.preview(task,1,new AbortController().signal)).corrected,false)
})
test('masked denial keeps useful safe code and never logs response text', async()=>{
  const api=new BusinessApi( (async()=>new Response(JSON.stringify({error:{code:'PREVIEW_MASK_UNAVAILABLE',message:'do-not-log-private-value'}}),{status:403})) as typeof fetch)
  await assert.rejects(api.preview(task,1,new AbortController().signal),e=>e instanceof ApiFailure && e.card.code==='PREVIEW_MASK_UNAVAILABLE' && !JSON.stringify(e.card).includes('do-not-log'))
})
test('review 409 is not retried and request remains exact change payload', async()=>{
  let calls=0;let captured=''
  const api=new BusinessApi((async(_input,init)=>{calls++;captured=String(init?.body);return new Response(JSON.stringify({error:{code:'RESULT_VERSION_CONFLICT'}}),{status:409})})as typeof fetch)
  const body={run_id:id,expected_revision:3,fields:{name:'合成测试'}}
  await assert.rejects(api.review(id,body,new AbortController().signal))
  assert.equal(calls,1);assert.deepEqual(JSON.parse(captured),body)
})

test('export sends exact selected versions and returns an XLSX Blob without retry', async()=>{
  let calls=0;let body:Record<string,unknown>={}
  const api=new BusinessApi((async(_input,init)=>{calls++;body=JSON.parse(String(init?.body));return new Response(new Blob(['synthetic-xlsx']),{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}})})as typeof fetch)
  const versions=[{task_id:id,run_id:id,result_revision:3}]
  const blob=await api.export({task_ids:[id],masked:false,reason:'合成验收',versions},new AbortController().signal)
  assert.equal(await blob.text(),'synthetic-xlsx');assert.equal(calls,1)
  assert.deepEqual(body,{task_ids:[id],masked:false,reason:'合成验收',versions,format:'xlsx'})
})

test('new result shapes keep member sources and reject malformed generic values',()=>{
  const base={task_id:id,run_id:id,result_revision:3,status:'NEED_REVIEW',review_issues:[]}
  const field={key:'name',label:'姓名',value:null,confidence:null,confidence_method:'unavailable',need_review:true,review_issues:[],source:{page:2}}
  const household=parseResult({...base,doc_type:'HOUSEHOLD_REGISTER',members:[{name:field}]})
  assert.equal(household.members?.[0]?.name?.source?.page,2)
  assert.throws(()=>parseResult({...base,doc_type:'HOUSEHOLD_REGISTER',members:[{name:'wrong'}]}))
  assert.equal(parseResult({...base,doc_type:'GENERIC',generic:{full_text:'合成',key_values:[{key:'测试',value:null}]}}).generic?.key_values[0]?.value,null)
  assert.throws(()=>parseResult({...base,doc_type:'GENERIC',generic:{full_text:'合成',key_values:[{key:'测试',value:12}]}}))
})
