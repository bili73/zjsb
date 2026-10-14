import test from 'node:test'
import assert from 'node:assert/strict'
import { genericDraft, genericPairSource } from '../src/generic-review.ts'
import { parseResult } from '../src/business.ts'

const id='11111111-2222-4333-8444-555555555555'
const other='22222222-2222-4333-8444-555555555555'
const source={page:1,bbox:[.1,.2,.8,.3],bbox_kind:'cell' as const,extraction_method:'ocr' as const}
const original={full_text:'初始正文',key_values:[{pair_id:id,key:'姓名',value:'张三',source},{pair_id:other,key:'姓名',value:null}]}

test('generic edits retain stable source links across duplicates and preserve manual values',()=>{
  const result={generic:original}
  const draft=genericDraft(result)
  assert.equal(draft.key_values[0]?.source_pair_id,id)
  draft.key_values.reverse();draft.key_values[1]!.value='人工修正'
  assert.equal(genericPairSource(result,draft.key_values[1]!),source)
  assert.equal(original.key_values[0]?.value,'张三')
  assert.deepEqual(genericDraft({...result,reviewed_generic:draft}),draft)
  assert.equal(genericPairSource(result,{key:'人工新增',value:'001'}),undefined)
})

test('legacy manual pairs never acquire a source by matching array position',()=>{
  const saved={full_text:'',key_values:[{key:'人工字段',value:null}]}
  assert.deepEqual(genericDraft({generic:original,reviewed_generic:saved}),saved)
  assert.deepEqual(genericDraft({reviewed_generic:{full_text:'',key_values:[]}}),{full_text:'',key_values:[]})
  assert.deepEqual(genericDraft({generic:{full_text:'旧正文',key_values:[{key:'名字',value:'李四'}]}}),
    {full_text:'旧正文',key_values:[{key:'名字',value:'李四'}]})
})

test('generic result contract accepts old data and validates optional original sources',()=>{
  const base={task_id:id,run_id:id,result_revision:0,doc_type:'GENERIC',status:'NEED_REVIEW',review_issues:[]}
  assert.equal(parseResult({...base,generic:original}).generic?.key_values.length,2)
  assert.ok(parseResult({...base,generic:{full_text:'旧正文',key_values:[]}}))
  assert.ok(parseResult({...base,generic:{...original,blocks:[{text:'原文',raw_text:'<b>原文</b>',page:1,source}],tables:[{rows:[['标签','值']],merges:[],source}]}}))
  for(const pair of [{...original.key_values[0],pair_id:'bad'},
    {...original.key_values[0],source:{...source,bbox:[0,.2,2,.3]}}]) {
    assert.throws(()=>parseResult({...base,generic:{...original,key_values:[pair]}}),/INVALID_RESPONSE/)
  }
})
