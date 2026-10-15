import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const require=createRequire(import.meta.url)
const {parse,compileScript}=require('@vue/compiler-sfc'), ts=require('typescript')
const vue=await import(pathToFileURL(require.resolve('vue')).href)
const sourcePath=fileURLToPath(new URL('../src/components/TableReview.vue',import.meta.url))
const source=(await readFile(sourcePath,'utf8')).replace('</script>',
  'defineExpose({ draft, mergeSpans, visibleRows, page, startRow, change, save, edited })\n</script>')
const compiled=compileScript(parse(source,{filename:sourcePath}).descriptor,{id:'table-review-test'})
const dataUrl=(code:string)=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const stub=dataUrl('export const ElMessageBox={async confirm(){}}')
const code=ts.transpileModule(compiled.content,{
  compilerOptions:{target:ts.ScriptTarget.ESNext,module:ts.ModuleKind.ESNext},
}).outputText.replace(/from ['"]([^'"]+)['"]/g,(_:string,specifier:string)=>{
  const resolved=specifier.startsWith('.')?path.resolve(path.dirname(sourcePath),specifier):require.resolve(specifier)
  return `from '${specifier==='element-plus'?stub:pathToFileURL(resolved).href}'`
})
const Component=(await import(dataUrl(code))).default
Component.render=()=>null
const renderer=vue.createRenderer({patchProp(){},insert(){},remove(){},createElement(){return{}},
  createText(){return{}},createComment(){return{}},setText(){},setElementText(){},parentNode(){return null},nextSibling(){return null}})

function mount() {
  const original={table_id:'00000000-0000-4000-8000-000000000001',title:'Synthetic',header_rows:1,
    rows:Array.from({length:120},()=>Array<string>(4).fill('')),
    merges:[{row:48,column:0,rowspan:5,colspan:2}],partial_acknowledged:false,
    title_candidates:[],outside_text:[],quality_warnings:[],incomplete:false,
    source:{page:1,bbox:[0,0,1,1],extraction_method:'ocr'},candidates:[],confidence:null}
  original.rows[48]![0]='merged anchor'
  const saved:any[]=[]
  const app=renderer.createApp(Component,{result:{tables:[original],run_id:'run',result_revision:7},
    canWrite:true,busy:false,onSave:(body:unknown)=>saved.push(body)})
  app.mount({})
  return {app,original,saved,e:app._instance.exposed}
}

test('actual table component caches spans across text edits and performs one lookup per visible cell',()=>{
  const h=mount()
  try {
    const index=h.e.mergeSpans.value
    let lookups=0
    const get=index.get.bind(index)
    index.get=(key:string)=>{lookups++;return get(key)}
    const first=h.e.visibleRows.value
    assert.equal(first.length,53)
    assert.equal(lookups,53*4)
    assert.deepEqual(first[48][0],{rowspan:5,colspan:2})
    assert.equal(first[49][0],null)
    h.e.draft.value.rows[0][3]='edited text'
    assert.equal(h.e.mergeSpans.value,index)
    assert.equal(h.e.visibleRows.value.length,53)
    assert.equal(lookups,2*53*4)
    h.e.page.value=2
    assert.equal(h.e.startRow.value,48)
    assert.deepEqual(h.e.visibleRows.value[0][0],{rowspan:5,colspan:2})
    assert.equal(h.e.mergeSpans.value,index)
    h.e.draft.value.merges[0].rowspan=6
    assert.notEqual(h.e.mergeSpans.value,index)
    assert.deepEqual(h.e.visibleRows.value[0][0],{rowspan:6,colspan:2})
    assert.equal(h.original.rows[0]![3],'')
  } finally {h.app.unmount()}
})

test('actual structural edit rebuilds spans and saves the same draft values with revision fences',async()=>{
  const h=mount()
  try {
    const before=h.e.mergeSpans.value
    h.e.draft.value.rows[0][3]='=literal'
    await h.e.change('row')
    assert.notEqual(h.e.mergeSpans.value,before)
    assert.deepEqual(h.e.visibleRows.value[49][0],{rowspan:5,colspan:2})
    assert.equal(h.e.visibleRows.value[50][0],null)
    assert.equal(h.e.edited.value,true)
    h.e.save()
    assert.equal(h.saved.length,1)
    assert.equal(h.saved[0].run_id,'run')
    assert.equal(h.saved[0].expected_revision,7)
    assert.equal(h.saved[0].tables[0].rows[1][3],'=literal')
    assert.equal(h.saved[0].tables[0].merges[0].row,49)
    assert.equal(h.original.merges[0]!.row,48)
  } finally {h.app.unmount()}
})
