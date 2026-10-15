import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { buildSpanIndex, cellSpan, editAxis, mergeSelection, responseFilename, rowWindow, tableDraft, validTableResponse, validateGrid } from '../src/table-review.ts'
import type { PhotoTable, TableDraft } from '../src/table-review.ts'

const make=():PhotoTable=>({table_id:'00000000-0000-4000-8000-000000000001',title:'',title_candidates:[{text:'标题建议',box:[1,2,3,4]}],header_rows:null,header_suggestion:1,rows:[['编号','备注'],['001',''],['001','=1+1']],merges:[],partial_acknowledged:false,source:{page:1,bbox:[0,0,1,1],extraction_method:'ocr'},candidates:[],outside_text:[],quality_warnings:[],incomplete:false,confidence:null})
test('photo-table edits accept Vue proxies and keep original values and blank cells intact',()=>{
  const original=make(),draft=reactive(tableDraft(original))
  assert.equal(draft.title,'标题建议');assert.equal(draft.header_rows,null)
  let next=editAxis(draft,'row',1);next.rows[1]![0]='0002'
  assert.deepEqual(original.rows,[['编号','备注'],['001',''],['001','=1+1']])
  next=editAxis(next,'column',1)
  assert.deepEqual(next.rows[3],['001','','=1+1'])
  next=editAxis(next,'column',1,true);next=editAxis(next,'row',1,true)
  assert.deepEqual(next.rows,original.rows)
  assert.equal(tableDraft(original,{...draft,title:''}).title,'')
})
test('supported header suggestions populate only new drafts including zero, never saved edits',()=>{
  for (const [count,source] of [[1,'structure'],[2,'model_tags'],[0,'data_rows']] as const) {
    const original={...make(),header_suggestion:count,header_suggestion_source:source}
    const draft=tableDraft(original)
    assert.equal(draft.header_rows,count)
    assert.equal(original.header_rows,null)
    for (const edited of [0,1,2,null]) {
      const saved={...draft,header_rows:edited}
      assert.equal(tableDraft(original,saved).header_rows,edited)
    }
  }
  const old=make()
  assert.equal(tableDraft(old).header_rows,null)
  for (const bad of [null,-1,4,1.5]) {
    assert.equal(tableDraft({...old,header_suggestion:bad,header_suggestion_source:'structure'}).header_rows,null)
  }
  assert.equal(tableDraft({...old,header_suggestion_source:'structure',incomplete:true}).header_rows,null)
  assert.equal(tableDraft({...old,header_suggestion_source:null}).header_rows,null)
})
test('title defaults require one distinct candidate and never refill an intentionally empty saved title',()=>{
  const original={...make(),header_suggestion_source:'structure' as const}
  assert.equal(tableDraft(original).title,'标题建议')
  assert.equal(tableDraft({...original,title_candidates:[]}).title,'')
  assert.equal(tableDraft({...original,title_candidates:[...original.title_candidates,{text:'另一候选',box:[1,2,3,4]}]}).title,'')
  assert.equal(tableDraft({...original,title_candidates:[...original.title_candidates,{text:' 标题建议 ',box:[1,2,3,4]}]}).title,'标题建议')
  const saved={...tableDraft(original),title:'',header_rows:null}
  assert.equal(tableDraft(original,saved).title,'')
  assert.equal(tableDraft({...original,partial_acknowledged:true}).partial_acknowledged,false)
})
test('merge edits preserve topology and reject silent text loss',()=>{
  let draft:TableDraft=tableDraft(make());draft.header_rows=1
  assert.throws(()=>mergeSelection(draft,0,0,0,1),/覆盖/)
  draft=mergeSelection(draft,1,0,1,1)
  assert.equal(cellSpan(buildSpanIndex(draft.merges),1,1),null)
  draft=editAxis(draft,'column',1)
  assert.deepEqual(draft.merges,[{row:1,column:0,rowspan:1,colspan:3}])
  draft=editAxis(draft,'row',0)
  assert.equal(draft.merges[0]!.row,2);assert.equal(draft.header_rows,2)
  assert.throws(()=>editAxis({...draft,rows:[['x']],merges:[],header_rows:0},'row',0,true))
})
test('row pages include complete merged spans and validate malformed grids',()=>{
  const draft=tableDraft(make());draft.rows=Array.from({length:120},()=>['',''])
  draft.merges=[{row:48,column:0,rowspan:5,colspan:1}]
  assert.deepEqual(rowWindow(draft,1),[0,53]);assert.deepEqual(rowWindow(draft,2),[48,100])
  assert.equal(validateGrid(draft),null)
  draft.rows[50]![0]='hidden';assert.match(validateGrid(draft)!,/覆盖/)
})
test('indexed spans preserve anchors, covered cells and ordinary cells at the supported grid limit',()=>{
  const draft=tableDraft(make())
  draft.rows=Array.from({length:1000},()=>Array<string>(10).fill(''))
  draft.merges=Array.from({length:5000},(_,i)=>({row:Math.floor(i/5),column:(i%5)*2,rowspan:1,colspan:2}))
  assert.equal(validateGrid(draft),null)
  const spans=buildSpanIndex(draft.merges)
  assert.equal(spans.size,10000)
  for (let row=0;row<1000;row++) for(let column=0;column<10;column++)
    assert.deepEqual(cellSpan(spans,row,column),column%2===0?{rowspan:1,colspan:2}:null)
  const unmerged=buildSpanIndex([])
  assert.deepEqual(cellSpan(unmerged,0,0),{rowspan:1,colspan:1})
  assert.deepEqual(cellSpan(unmerged,999,9),{rowspan:1,colspan:1})
})
test('table response validation and download filenames reject malformed payloads',()=>{
  const original=make();assert.ok(validTableResponse({tables:[original]}))
  assert.equal(validTableResponse({tables:[{...original,rows:[['x'],[]]}]}),false)
  assert.equal(validTableResponse({tables:[{...original,merges:[{}]}]}),false)
  assert.equal(validTableResponse({tables:[original],reviewed_tables:[{...tableDraft(original),table_id:'other'}]}),false)
  assert.equal(responseFilename("attachment; filename*=UTF-8''%E8%A1%A8%E6%A0%BC.xlsx"),'表格.xlsx')
  for(const name of ['../x.xlsx','a\\b.xlsx','x.exe','%x.xlsx','bad\nx.zip']) {
    const header=name.startsWith('%')?`attachment; filename*=UTF-8''${name}`:`attachment; filename="${name}"`
    assert.equal(responseFilename(header),null)
  }
})
