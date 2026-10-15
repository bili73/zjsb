<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { FieldSource, TaskResult } from '../business.ts'
import type { ReviewBody } from '../review.ts'
import { buildSpanIndex, cellSpan, copyDraft, editAxis, mergeSelection, rowWindow, supportedHeaderSuggestion, tableDraft, validateGrid } from '../table-review.ts'

const props=defineProps<{ result: TaskResult; canWrite: boolean; busy: boolean }>()
const emit=defineEmits<{ (e:'dirty', value:boolean):void; (e:'save', body:ReviewBody):void; (e:'locate', source:FieldSource):void }>()
const original=props.result.tables?.[0]
const draft=ref(original ? tableDraft(original,props.result.reviewed_tables?.[0]) : null)
const initialDraft=JSON.stringify(draft.value)
const edited=computed(()=>JSON.stringify(draft.value)!==initialDraft)
const headerSuggestion=original ? supportedHeaderSuggestion(original) : null
const headerBasis=({model_tags:'模型表头标记',structure:'合并层级与数据结构',data_rows:'连续序号与数据结构'})[original?.header_suggestion_source ?? 'structure']
const selected=ref({row:0,column:0}), endRow=ref(1), endColumn=ref(1), page=ref(1), error=ref('')
const disabled=computed(() => !props.canWrite || props.busy)
// 必填未填标红：标题、表头确认、不完整表格确认是导出的硬性条件（对应后端 MISSING / INCOMPLETE_OUTPUT）。
const titleMissing=computed(() => !!draft.value && !draft.value.title.trim())
const headerMissing=computed(() => !!draft.value && draft.value.header_rows === null)
const partialMissing=computed(() => !!draft.value && !!original?.incomplete && !draft.value.partial_acknowledged)
const windowRows=computed(() => draft.value ? rowWindow(draft.value,page.value) : [0,0])
const startRow=computed(()=>windowRows.value[0] ?? 0)
const mergeSpans=computed(() => buildSpanIndex(draft.value?.merges ?? []))
const visibleRows=computed(() => draft.value?.rows.slice(startRow.value,windowRows.value[1])
  .map((row,ri)=>row.map((_,ci)=>cellSpan(mergeSpans.value,startRow.value+ri,ci))) ?? [])
function dirty() { error.value=''; emit('dirty',edited.value) }
function choose(row:number,column:number) { selected.value={row,column};endRow.value=row+1;endColumn.value=column+1 }
async function change(axis:'row'|'column',remove=false,after=false) {
  if (!draft.value || disabled.value) return
  const index=selected.value[axis]+(after?1:0)
  if (remove) {
    const values=axis==='row' ? draft.value.rows[index]! : draft.value.rows.map(row=>row[index]!)
    if (values.some(v=>v!=='')) { try { await ElMessageBox.confirm('所选行/列包含内容，删除后需要手动重新填写。是否删除？','删除表格内容') } catch { return } }
  }
  try {
    draft.value=editAxis(draft.value,axis,index,remove)
    choose(Math.min(axis==='row'?index:selected.value.row,draft.value.rows.length-1),Math.min(axis==='column'?index:selected.value.column,draft.value.rows[0]!.length-1))
    page.value=Math.floor(selected.value.row/50)+1;dirty()
  }
  catch (e) { error.value=(e as Error).message }
}
function merge() {
  if (!draft.value || disabled.value) return
  try { draft.value=mergeSelection(draft.value,selected.value.row,selected.value.column,endRow.value-1,endColumn.value-1);dirty() }
  catch (e) { error.value=(e as Error).message }
}
function unmerge() {
  if (!draft.value || disabled.value) return
  const {row,column}=selected.value
  draft.value.merges=draft.value.merges.filter(m=>!(row>=m.row&&row<m.row+m.rowspan&&column>=m.column&&column<m.column+m.colspan));dirty()
}
function navigate(event:KeyboardEvent,row:number,column:number) {
  if (!event.altKey || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key) || !draft.value) return
  event.preventDefault()
  const r=Math.max(0,Math.min(draft.value.rows.length-1,row+(event.key==='ArrowDown'?1:event.key==='ArrowUp'?-1:0)))
  const c=Math.max(0,Math.min(draft.value.rows[0]!.length-1,column+(event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0)))
  document.getElementById(`table-cell-${r}-${c}`)?.focus()
}
function save() {
  if (!draft.value || disabled.value) return
  error.value=validateGrid(draft.value) ?? ''
  if (!error.value) emit('save',{run_id:props.result.run_id,expected_revision:props.result.result_revision,tables:[copyDraft(draft.value)]})
}
</script>
<template>
  <section class="table-review">
    <el-alert v-if="!original || !draft" type="warning" :closable="false">未获得可编辑表格，请重新识别或调整主体后新建任务。</el-alert>
    <template v-else>
      <h3>表格核对</h3>
      <el-alert v-if="edited" type="warning" :closable="false">有未保存的修正，请保存后导出。</el-alert>
      <el-alert v-else-if="result.export_ready" type="success" :closable="false">可以直接下载 Excel，无需再点保存。请自行核对识别内容。</el-alert>
      <p v-for="warning in original.quality_warnings" :key="warning" class="conf">{{ warning }}</p>
      <div class="table-tools"><el-button @click="emit('locate',original.source)">查看已识别主体</el-button><el-button v-for="(candidate,i) in original.candidates" :key="i" @click="emit('locate',{...original.source,bbox:candidate.bbox})">候选 {{ i+1 }}</el-button></div>
      <el-form label-position="top" :disabled="disabled">
        <el-form-item label="表格标题（Excel 文件名）" :class="{ 'field-missing': titleMissing }"><el-input v-model="draft.title" maxlength="200" placeholder="确认标题，也可以手动填写" @input="dirty" /></el-form-item>
        <div class="table-tools"><el-button v-for="candidate in original.title_candidates" :key="candidate.text" size="small" @click="draft.title=candidate.text;dirty()">采用：{{ candidate.text }}</el-button></div>
        <p v-if="titleMissing" class="conf">{{ original.title_candidates.length>1 ? '存在多个标题候选，请选择或填写后保存。' : '尚未识别到标题，请填写后保存。' }}</p>
        <el-form-item label="表头行数（从第一行起；无表头填0）" :class="{ 'field-missing': headerMissing }"><el-input-number v-model="draft.header_rows" :min="0" :max="draft.rows.length" :precision="0" aria-label="表头行数" @change="dirty" /></el-form-item>
        <p v-if="headerSuggestion !== null" class="conf">根据{{ headerBasis }}，建议{{ headerSuggestion === 0 ? '无表头（0行）' : `前 ${headerSuggestion} 行为表头` }}。{{ props.result.reviewed_tables?.length ? '当前保留已保存的设置。' : '已自动填写，可对照高亮行修改。' }}有修改时再保存。</p>
        <p v-else class="conf">无法可靠判断表头行数，请对照原图手动设置；无表头填0。</p>
      </el-form>
      <el-alert v-if="original.outside_text.length" type="warning" :closable="false"><b>表外识别到文字，请核对是否需要补成一行：</b><p v-for="(snippet,i) in original.outside_text" :key="i" class="outside-text">{{ snippet.text }}</p></el-alert>
      <p>共 {{ draft.rows.length }} 行 × {{ draft.rows[0]?.length }} 列（含表头）。点击单元格选择位置；Tab 或 Alt + 方向键换格。</p>
      <div class="table-tools"><span>当前：第 {{ selected.row+1 }} 行、第 {{ selected.column+1 }} 列</span><el-button :disabled="disabled" @click="change('row')">上方插行</el-button><el-button :disabled="disabled" @click="change('row',false,true)">下方插行</el-button><el-button :disabled="disabled" @click="change('column')">左侧插列</el-button><el-button :disabled="disabled" @click="change('column',false,true)">右侧插列</el-button><el-button :disabled="disabled" @click="change('row',true)">删除行</el-button><el-button :disabled="disabled" @click="change('column',true)">删除列</el-button></div>
      <div class="table-tools"><span>从选中格合并到</span><el-input-number v-model="endRow" :min="selected.row+1" :max="draft.rows.length" :precision="0" :disabled="disabled" aria-label="合并结束行" /><span>行</span><el-input-number v-model="endColumn" :min="selected.column+1" :max="draft.rows[0]!.length" :precision="0" :disabled="disabled" aria-label="合并结束列" /><span>列</span><el-button :disabled="disabled" @click="merge">合并</el-button><el-button :disabled="disabled" @click="unmerge">拆分当前格</el-button></div>
      <div class="grid-scroll"><table class="photo-grid"><tbody><tr v-for="(row,ri) in visibleRows" :key="`${page}-${ri}`" :class="{header: startRow+ri<(draft.header_rows??0)}"><th>{{ startRow+ri+1 }}</th><template v-for="(span,ci) in row" :key="ci"><td v-if="span" :rowspan="span.rowspan" :colspan="span.colspan"><textarea :id="`table-cell-${startRow+ri}-${ci}`" v-model="draft.rows[startRow+ri]![ci]" :readonly="disabled" :aria-label="`第${startRow+ri+1}行第${ci+1}列`" @focus="choose(startRow+ri,ci)" @input="dirty" @keydown="navigate($event,startRow+ri,ci)" /></td></template></tr></tbody></table></div>
      <el-pagination v-if="draft.rows.length>50" v-model:current-page="page" :page-size="50" :total="draft.rows.length" layout="prev, pager, next" />
      <el-checkbox v-if="original.incomplete" :class="{ 'field-missing': partialMissing }" v-model="draft.partial_acknowledged" :disabled="disabled" @change="dirty">我已对照原图补正，或明确仅导出当前保留的部分内容。</el-checkbox>
      <p v-if="error" role="alert">{{ error }}</p>
      <el-button type="primary" :disabled="disabled || !edited" :loading="busy" @click="save">保存表格修正</el-button>
      <p class="conf">完整结果且标题、表头明确时可直接导出；仅修改后需要保存。允许保存未完成草稿；识别不完整时需补正或确认。空白格无需填写，原始识别记录保留。</p>
      <details><summary>查看初始识别内容（只读）</summary><pre>{{ original.rows.map(row=>row.join('\t')).join('\n') }}</pre></details>
    </template>
  </section>
</template>
<style scoped>
.table-review{padding:12px}.table-tools{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0}.table-tools .el-input-number{width:120px}.grid-scroll{overflow:auto;max-height:520px;margin:12px 0}.photo-grid{border-collapse:collapse}.photo-grid td,.photo-grid th{border:1px solid #cdd6df;vertical-align:top}.photo-grid th{min-width:36px;background:#edf1f6}.photo-grid textarea{display:block;border:0;min-width:105px;width:100%;min-height:42px;box-sizing:border-box;padding:8px;resize:vertical;font:inherit;background:transparent}.photo-grid .header td{background:#fff1e7}.photo-grid textarea:focus{outline:2px solid #ef760e;outline-offset:-2px}.outside-text{white-space:pre-wrap}.table-review [role=alert]{color:#b42318}
/* 必填未填红框：与 ReviewEditor 的标红样式一致。 */
.field-missing :deep(.el-input__wrapper){box-shadow:0 0 0 1px var(--el-color-danger) inset;background-color:var(--el-color-danger-light-9)}
.field-missing :deep(.el-form-item__label){color:var(--el-color-danger)}
.field-missing :deep(.el-checkbox__inner){box-shadow:0 0 0 1px var(--el-color-danger)}
.field-missing :deep(.el-checkbox__label){color:var(--el-color-danger)}
</style>

