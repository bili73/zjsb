<script setup lang="ts">
import { householdMemberLabels as memberLabels } from '../business.ts'
import { memberFieldRequired } from '../requiredFields.ts'
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { genderText, isGenderKey, isMedicalReviewItem, medicalProjectCount } from '../business.ts'
import { numberLengthHint } from '../numberLength.ts'
import { InfoFilled } from '@element-plus/icons-vue'
import type { DocProfile, Field, FieldSource, TaskResult } from '../business.ts'
import { addedMember, buildReview, canAcceptIssue, changedValues, collectIssues, looksMasked, memberFields, summaryPatch } from '../review.ts'
import type { ReviewBody, Scalar, IssueJump } from '../review.ts'
import { genericDraft, genericPairSource } from '../generic-review.ts'
import { revealAnchor } from '../reveal.ts'
const props = defineProps<{ result: TaskResult; profile?: DocProfile; canWrite: boolean; busy: boolean; pageCount: number; regions?: { region_id: string; page: number }[]; focus?: (IssueJump & { seq: number }) | null }>()
const emit = defineEmits<{ (e: 'save', body: ReviewBody): void; (e: 'dirty', value: boolean): void; (e: 'locate', source: FieldSource): void }>()
const fields = computed(() => props.result.fields ?? Object.values(props.result.basic_info ?? {}))
const values = reactive<Record<string, Scalar>>(Object.fromEntries(fields.value.map(f => [f.key, f.value])))
const lengthHints = computed(() => Object.fromEntries(fields.value.map(field => [field.key, numberLengthHint(props.result.doc_type, field.key, values[field.key])])))
const projectCount = computed(() => medicalProjectCount(values.exam_projects))
const editable = (key: string) => (props.profile?.fields.find(f => f.key === key)?.editable ?? fields.value.find(f => f.key === key)?.editable) !== false
const itemKeys = ['name', 'alias', 'category', 'result_raw', 'unit', 'reference_range', 'reported_abnormal_marker', 'risk_grade', 'diagnosis'] as const
const itemLabels: Record<string, string> = { name: '项目名称', alias: '别名', category: '类别', result_raw: '检测结果原文', unit: '单位', reference_range: '参考范围', reported_abnormal_marker: '报告标记', risk_grade: '报告等级', diagnosis: '异常诊断' }
const reviewItems = computed(() => (props.result.items ?? []).filter(isMedicalReviewItem))
const items = reactive(reviewItems.value.map(i => ({ item_id: i.item_id, values: Object.fromEntries(itemKeys.map(k => [k, i[k] ?? ''])), removed: false })))
const added = ref<Record<string, string>[]>([])
const findings = reactive((props.result.report_summary?.findings ?? []).map(f => ({ finding_id: f.finding_id, values: { text: f.text, risk_grade: f.risk_grade ?? '', diagnosis: f.diagnosis ?? '' }, removed: false, result_item_id: undefined as string | null | undefined })))
const members = reactive((props.result.members ?? []).map(m => ({ values: Object.fromEntries(memberFields(m).map(f => [f.key, f.value])) as Record<string, Scalar>, removed: false })))
const addedMembers = ref<{fields:Record<string,Scalar>;source_page:number}[]>([])
const originalGeneric = genericDraft(props.result)
const generic = reactive(genericDraft(props.result))
const coverageEnabled = ref(false), checkedPages = ref<number[]>([]), coverageReason = ref('')
const regionActions = reactive<Record<string, '' | 'TRANSCRIBED' | 'NO_CONTENT'>>({})
const regionReasons = reactive<Record<string, string>>({}), regionItems = reactive<Record<string, string[]>>({})
const summaryEnabled = ref(false), summaryReason = ref(''), summaryPage = ref<number>(1), summaryCount = ref<number | undefined>(props.result.report_summary?.declared_count ?? undefined)
const summaryScope = ref(props.result.report_summary?.scope ?? 'unidentified'), summaryTitle = ref('')
const addedFindings = ref<{ text: string; risk_grade: string; diagnosis: string; result_item_id?: string }[]>([])
const regionFields = reactive<Record<string,string[]>>({}), regionAdded = reactive<Record<string,number[]>>({}), regionFindings = reactive<Record<string,string[]>>({}), regionMembers = reactive<Record<string,number[]>>({}), regionGeneric = reactive<Record<string,boolean>>({})
const message = ref('')
const regionAddedMembers = reactive<Record<string,number[]>>({})
watch([addedMembers, summaryScope, summaryTitle, regionAddedMembers], () => emit('dirty',true), {deep:true})
const issues = computed(() => collectIssues(props.result))
const required = (key: string) => fields.value.find(f => f.key === key)?.required ?? props.profile?.fields.find(f => f.key === key)?.required === true
// 缺失必填：值为空（null/'' 视为缺，false 与 0 是已填写），用于给输入框标红边。
const isMissing = (value: unknown) => value === null || value === undefined || value === ''
const missingRequired = (key: string) => required(key) && isMissing(values[key])
const memberMissing = (member: { values: Record<string, Scalar> }, key: string) => memberFieldRequired(props.result, key) && isMissing(member.values[key])
const addedMemberMissing = (member: { fields: Record<string, Scalar> }, key: string) => memberFieldRequired(props.result, key) && isMissing(member.fields[key])
// 户口本成员是核对主对象：标题携带人数与必填缺失摘要，存在缺失时默认展开，避免“没识别出人”的误判。
const membersWithMissing = computed(() => members.reduce((count, member, index) => {
  const original = props.result.members?.[index]
  return original && memberFields(original).some(field => memberMissing(member, field.key)) ? count + 1 : count
}, 0))
const memberTitle = computed(() => members.length ? `户口本成员（${members.length} 人${membersWithMissing.value ? `，${membersWithMissing.value} 人必填缺失` : ''}）` : '户口本成员（未识别到成员）')
const memberOpen = ref<string[]>(membersWithMissing.value ? ['members'] : [])
// 顶部红字点击定位：目标所在折叠面板先展开，再滚动到锚点并闪烁一次；items/findings 默认收起，需要受控展开。
const openPanels = ref<string[]>([])
let revealGeneration = 0
onBeforeUnmount(() => { revealGeneration++ })
async function revealEditorAnchor(id: string) {
  const generation = ++revealGeneration
  await nextTick()
  const anchor = document.getElementById(id)
  if (!anchor) return
  const panel = anchor.closest('.el-collapse-item')?.querySelector<HTMLElement>('.el-collapse-item__wrap')
  if (panel) {
    // Element Plus starts expansion in rAF; nextTick alone still leaves the collapsed scroll range.
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
    if (generation !== revealGeneration || !anchor.isConnected) return
    await Promise.allSettled(panel.getAnimations().map(animation => animation.finished))
    // Let the transition cleanup commit its final height before scrolling once.
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
  }
  if (generation !== revealGeneration || !anchor.isConnected || panel?.getAttribute('aria-hidden') === 'true') return
  revealAnchor(anchor)
}
const anchorId = (focus: IssueJump) => focus.kind === 'field' ? `rev-field-${focus.id}` : focus.kind === 'item' ? `rev-item-${focus.id}` : focus.kind === 'finding' ? `rev-finding-${focus.id}` : `rev-member-${focus.id}`
watch(() => props.focus, focus => {
  revealGeneration++
  if (!focus) return
  if (focus.kind === 'item' && !openPanels.value.includes('items')) openPanels.value = [...openPanels.value, 'items']
  if (focus.kind === 'finding' && !openPanels.value.includes('findings')) openPanels.value = [...openPanels.value, 'findings']
  if (focus.kind === 'member' && !memberOpen.value.includes('members')) memberOpen.value = [...memberOpen.value, 'members']
  void revealEditorAnchor(anchorId(focus))
})
// 体检的核对主对象是检测项目与清单：折叠标题带上数量与异常摘要，主对象不必点开才知道。
const itemsTitle = computed(() => {
  const stats = props.result.stats
  const flags: string[] = []
  if (stats?.abnormal) flags.push(`${stats.abnormal} 项异常`)
  if (stats?.unknown) flags.push(`${stats.unknown} 项待判定`)
  const extra = added.value.length ? `，另新增 ${added.value.length}` : ''
  return `编辑检测项目 / 增删项目（${reviewItems.value.length} 项${flags.length ? `：${flags.join('、')}` : ''}${extra}）`
})
const findingsTitle = computed(() => `编辑报告检查治疗清单（${findings.length} 条）`)
const summaryEditTitle = computed(() => `清单声明数 / 增删条目（声明 ${props.result.report_summary?.declared_count ?? '数量未声明'}）`)
// 不能一键确认的字段级异议就地红字提示，与结果表格、顶部红字三处呼应。
const fieldIssues = (field: Field) => (field.review_issues ?? []).filter(issue => !canAcceptIssue(issue))
// 键值是人工补录结果的一部分：删除前确认一次，与表格页删行/列的标准一致。
async function removePair(index: number) {
  try { await ElMessageBox.confirm('删除后如需恢复需要重新手动填写，确认删除该键值？', '删除键值', { type: 'warning' }) }
  catch { return }
  generic.key_values.splice(index, 1)
}
const genericFullTextRequired = computed(() => props.result.required_field_keys?.includes('generic.full_text') ?? true)
function setField(key: string, value: string) { const kind=props.profile?.fields.find(f=>f.key===key)?.type; values[key]=value===''?null:kind==='integer'||kind==='number'?Number(value):kind==='boolean'?value==='true':value }
const fieldKind = (key: string) => props.profile?.fields.find(f=>f.key===key)?.type
watch([values, items, added, findings, members, generic, coverageEnabled, checkedPages, coverageReason, regionActions, regionReasons, regionItems, regionFields, regionAdded, regionFindings, regionMembers, regionGeneric, summaryEnabled, summaryReason, summaryPage, summaryCount, addedFindings], () => emit('dirty', true), { deep: true })
// 新增项目的空值判定在提交与指位两处共用，避免两份条件各自漂移。
const invalidAddedItem = (item: Record<string, string>) => !item.name?.trim() || !item.result_raw?.trim() || Object.values(item).some(looksMasked)
// 保存被本地校验拦下时，文案说明「哪里错了」，这里把人带到「哪里改」：展开对应折叠面板并滚动到出错块，与顶部红字跳转同一机制。
function saveErrorTarget(code: string): { panel?: string; id: string } | null {
  if (code === 'INVALID_ITEM') { const index = added.value.findIndex(invalidAddedItem); return index >= 0 ? { panel: 'items', id: `rev-added-${index}` } : null }
  if (code === 'GENERIC_MASKED') return { id: 'rev-generic' }
  if (code === 'MEMBER_SOURCE') return { panel: 'new-members', id: 'rev-new-members' }
  if (code === 'SUMMARY' || code === 'SUMMARY_SOURCE' || code === 'SUMMARY_COUNT' || code === 'SUMMARY_TITLE') return { panel: 'summary-edit', id: 'rev-summary' }
  if (code === 'COVERAGE') return { panel: 'coverage', id: 'rev-coverage' }
  return null
}
function revealSaveError(code: string) {
  const target = saveErrorTarget(code)
  if (!target) return
  if (target.panel && !openPanels.value.includes(target.panel)) openPanels.value = [...openPanels.value, target.panel]
  void revealEditorAnchor(target.id)
}
function save() {
  revealGeneration++
  message.value = ''
  try {
    const body = buildReview(props.result, { fields: values, confirm_export_disputes: true, accepted_issues: issues.value.filter(row => canAcceptIssue(row.issue)).map(row => ({ issue_id: row.issue.issue_id })) })
    body.items = items.filter(i => !i.removed).flatMap(i => {
      const old = props.result.items!.find(o => o.item_id === i.item_id)!
      const changed = changedValues(old as unknown as Record<string, unknown>, i.values)
      if (Object.hasOwn(changed, 'result_raw')) changed.result_raw = i.values.result_raw
      return Object.keys(changed).length ? [{ item_id: i.item_id, ...changed }] : []
    })
    body.removed_item_ids = items.filter(i => i.removed).map(i => i.item_id)
    body.added_items = added.value.map(item => {
      if (invalidAddedItem(item)) throw new Error('INVALID_ITEM')
      return { ...item }
    })
    body.findings = findings.filter(f=>!f.removed).flatMap(f => {
      const old = props.result.report_summary!.findings.find(o => o.finding_id === f.finding_id)!
      const change = changedValues(old as unknown as Record<string, unknown>, f.values)
      if (f.result_item_id !== undefined) change.result_item_id = f.result_item_id || null
      return Object.keys(change).length ? [{ finding_id: f.finding_id, ...change }] : []
    })
    body.members = members.flatMap((m, index) => {
      if(m.removed) return []
      const original = Object.fromEntries(memberFields(props.result.members![index]!).map(f => [f.key, f.value]))
      const change = changedValues(original, m.values) as Record<string, Scalar>
      return Object.keys(change).length ? [{ index, fields: change }] : []
    })
    body.removed_member_indexes = members.flatMap((member,index)=>member.removed?[index]:[])
    body.added_members = addedMembers.value.map(member=>addedMember(member.fields,member.source_page,props.pageCount,Object.keys(memberLabels).filter(key=>memberFieldRequired(props.result,key))))
    if (props.result.doc_type === 'GENERIC' && JSON.stringify(generic) !== JSON.stringify(originalGeneric)) {
      if (looksMasked(generic.full_text) || generic.key_values.some(k => looksMasked(k.value))) throw new Error('GENERIC_MASKED')
      body.generic = { full_text: generic.full_text, key_values: generic.key_values.map(k => ({ ...k })) }
    }
    if(summaryEnabled.value){
      const patch = summaryPatch(props.result.report_summary,summaryScope.value,summaryCount.value,summaryTitle.value,summaryReason.value,summaryPage.value,props.pageCount)
      patch.added_findings=addedFindings.value.map(f=>({...f,...(f.result_item_id?{}:{result_item_id:null})}))
      patch.removed_finding_ids=findings.filter(f=>f.removed).map(f=>f.finding_id)
      body.report_summary=patch
    }else if(findings.some(f=>f.removed)||addedFindings.value.length) throw new Error('SUMMARY')
    if (coverageEnabled.value) {
      if (!coverageReason.value.trim() || checkedPages.value.length !== props.pageCount || !props.pageCount) throw new Error('COVERAGE')
      body.coverage = { pages: [...checkedPages.value].sort((a, b) => a - b), reason: coverageReason.value, regions: Object.entries(regionActions).filter(([, action]) => action).map(([region_id, action]) => ({ region_id, action: action as 'TRANSCRIBED' | 'NO_CONTENT', reason: regionReasons[region_id] ?? '', ...(action === 'TRANSCRIBED' ? { item_ids: regionItems[region_id] ?? [], field_keys: regionFields[region_id] ?? [], added_item_indexes: regionAdded[region_id] ?? [], finding_ids: regionFindings[region_id] ?? [], member_indexes: regionMembers[region_id] ?? [], added_member_indexes: regionAddedMembers[region_id] ?? [], generic: regionGeneric[region_id] ?? false } : {}) })) }
    }
    emit('save', body)
  } catch (error) {
    const code = error instanceof Error ? error.message : ''
    message.value = code === 'MASKED_VALUE' || code === 'GENERIC_MASKED' ? '不能把掩码当作原始值提交。未改的掩码将跳过；需修正时请查看原件并输入完整值。'
      : code === 'INVALID_ITEM' ? '新增检测项目需要项目名称和检测结果。'
      : code === 'MEMBER_SOURCE' ? '新增成员需要姓名，且原件页必须在 1 到总页数之间。'
      : code === 'SUMMARY' ? '已新增或删除清单条目：请展开「清单声明数 / 增删条目」，勾选修正报告清单并填写理由与来源页。'
      : code === 'SUMMARY_SOURCE' ? '修正报告清单需要核对依据与有效来源页。'
      : code === 'SUMMARY_COUNT' ? '清单声明数量需为非负整数，未声明请留空。'
      : code === 'SUMMARY_TITLE' ? '修改清单声明数量或作用域时，需同时填写原清单标题。'
      : code === 'COVERAGE' ? '全页覆盖确认：请勾选全部页面并填写核对依据。'
      : '请检查填写内容后重试。'
    void revealSaveError(code)
  }
}
</script>
<template>
  <section class="review-editor">
    <h3 data-guide="review-fields">人工核对与修正</h3>
    <el-form label-position="top" :disabled="!canWrite || busy">
      <div class="field-grid">
        <el-form-item v-for="field in fields" :id="`rev-field-${field.key}`" :key="field.key" :class="{ 'field-missing': missingRequired(field.key) }" :label="`${field.label}${required(field.key) ? '（必填）' : ''}`">
          <el-select v-if="fieldKind(field.key) === 'boolean'" v-model="values[field.key]"><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select>
          <el-select v-else-if="isGenderKey(field.key)" :model-value="genderText(values[field.key])" placeholder="未识别" clearable @update:model-value="v => setField(field.key, v ?? '')"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select>
          <el-input v-else :type="['exam_projects','blood_routine','urine_routine','ecg','dr_imaging','abdominal_ultrasound','liver_function'].includes(field.key) ? 'textarea' : 'text'" :rows="3" :model-value="String((field.key === 'exam_project_count' ? projectCount : values[field.key]) ?? '')" :disabled="!editable(field.key)" @update:model-value="v => setField(field.key,v)" />
          <p v-if="lengthHints[field.key]" role="status" :class="['number-length-hint', lengthHints[field.key]?.level]">{{ lengthHints[field.key]?.message }}</p>
          <p v-for="issue in fieldIssues(field)" :key="issue.issue_id" role="status" class="field-issue">{{ issue.message }}</p>
          <div v-if="['BANK_CARD','BANK_CARD_COPY','INTERVIEW_FORM'].includes(result.doc_type) && field.candidates?.length" class="bank-candidates">
            <div v-for="(candidate,index) in field.candidates" :key="index" class="candidate-pick">
              <el-icon class="candidate-icon"><InfoFilled /></el-icon>
              <span class="candidate-body">
                <span v-if="candidate.reason" class="candidate-reason">{{ candidate.reason }}</span>
                <span class="candidate-value">{{ candidate.value }}</span>
              </span>
              <el-button v-if="candidate.source" link type="primary" size="small" @click="emit('locate',candidate.source)">查看来源</el-button>
              <el-button size="small" type="primary" plain @click="setField(field.key, String(candidate.value ?? ''))">采用</el-button>
            </div>
          </div>
          <el-button v-if="['BANK_CARD','BANK_CARD_COPY','INTERVIEW_FORM','HOUSEHOLD_REGISTER'].includes(result.doc_type) && field.source" link type="primary" @click="emit('locate', field.source)">查看来源</el-button>
          <el-button v-if="result.doc_type === 'MEDICAL_REPORT'" link type="primary" @click="emit('locate', field.source ?? {})">查看来源 / 整页</el-button>
        </el-form-item>
      </div>
      <el-collapse v-if="items.length || result.doc_type === 'MEDICAL_REPORT'" v-model="openPanels">
        <el-collapse-item :title="itemsTitle" name="items">
          <article v-for="(item, index) in items" :id="`rev-item-${item.item_id}`" :key="item.item_id" class="edit-row">
            <el-checkbox v-model="item.removed">删除该项目（提交后生效）</el-checkbox>
            <div v-if="!item.removed" class="field-grid"><el-form-item v-for="key in itemKeys" :key="key" :label="itemLabels[key]"><el-input v-model="item.values[key]" /></el-form-item></div>
            <el-button link type="primary" @click="emit('locate', reviewItems[index]?.source ?? {})">检测行来源</el-button>
            <el-button v-for="(source, si) in reviewItems[index]?.diagnosis_sources ?? []" :key="si" link type="primary" @click="emit('locate', source)">诊断来源 {{ si + 1 }}</el-button>
          </article>
          <article v-for="(item, index) in added" :key="index" :id="`rev-added-${index}`" class="edit-row"><div class="field-grid"><el-form-item v-for="key in itemKeys" :key="key" :label="itemLabels[key]"><el-input v-model="item[key]" /></el-form-item></div><el-button @click="added.splice(index,1)">撤销新增</el-button></article>
          <el-button @click="added.push(Object.fromEntries(itemKeys.map(k => [k,''])))">新增检测项目</el-button>
        </el-collapse-item>
      </el-collapse>
      <el-collapse v-if="findings.length" v-model="openPanels"><el-collapse-item :title="findingsTitle" name="findings"><article v-for="(finding,index) in findings" :id="`rev-finding-${finding.finding_id}`" :key="finding.finding_id" class="edit-row">
        <el-checkbox v-model="finding.removed">删除此清单条目（需下方清单修正理由与来源页）</el-checkbox>
        <el-form-item label="报告条目原文"><el-input v-model="finding.values.text" type="textarea" /></el-form-item>
        <div class="field-grid"><el-form-item label="报告等级"><el-input v-model="finding.values.risk_grade" /></el-form-item><el-form-item label="异常诊断"><el-input v-model="finding.values.diagnosis" /></el-form-item></div>
        <el-select v-model="finding.result_item_id" placeholder="检测结果关联保持不变"><el-option label="取消关联" :value="''" /><el-option v-for="item in result.items ?? []" :key="item.item_id" :value="item.item_id" :label="`${item.name} · ${item.result_raw}`" /></el-select>
        <el-button v-for="(source,si) in result.report_summary?.findings[index]?.sources ?? []" :key="si" link type="primary" @click="emit('locate',source)">清单来源 {{ si + 1 }}</el-button>
      </article></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'MEDICAL_REPORT'" v-model="openPanels"><el-collapse-item id="rev-summary" :title="summaryEditTitle" name="summary-edit"><el-checkbox v-model="summaryEnabled">修正报告清单（不影响实验室计数）</el-checkbox><template v-if="summaryEnabled"><el-select v-model="summaryScope" aria-label="清单作用域"><el-option label="需检查治疗清单" value="follow_up_required"/><el-option label="总检结论" value="overall_conclusion"/><el-option label="未识别" value="unidentified"/></el-select><el-input v-model="summaryTitle" placeholder="原报告清单标题（改声明数量或作用域时必填）"/><el-form-item label="原件明确声明数量；未声明留空，不用条目长度代填"><el-input-number :disabled="summaryScope !== 'follow_up_required'" v-model="summaryCount" :min="0" :precision="0" /></el-form-item><el-form-item label="声明或清单所在原件页"><el-input-number v-model="summaryPage" :min="1" :max="pageCount" :precision="0" /></el-form-item><el-input v-model="summaryReason" placeholder="说明修正的原件依据（必填）"/><article v-for="(f,index) in addedFindings" :key="index" class="edit-row"><el-input v-model="f.text" placeholder="清单条目原文"/><el-input v-model="f.risk_grade" placeholder="报告等级"/><el-input v-model="f.diagnosis" placeholder="异常诊断"/><el-select v-model="f.result_item_id" clearable placeholder="关联检测项目"><el-option v-for="item in result.items ?? []" :key="item.item_id" :label="item.name" :value="item.item_id"/></el-select><el-button @click="addedFindings.splice(index,1)">撤销新增</el-button></article><el-button @click="addedFindings.push({text:'',risk_grade:'',diagnosis:''})">新增清单条目</el-button></template></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'HOUSEHOLD_REGISTER'" v-model="memberOpen"><el-collapse-item :title="memberTitle" name="members"><article v-for="(member,index) in members" :id="`rev-member-${index}`" :key="index" class="edit-row"><h4>成员 {{ index + 1 }}</h4><el-checkbox v-model="member.removed">删除此成员（提交后生效）</el-checkbox><div v-if="!member.removed" class="field-grid"><el-form-item v-for="field in memberFields(result.members![index]!)" :key="field.key" :class="{ 'field-missing': memberMissing(member, field.key) }" :label="`${field.label}${memberFieldRequired(result, field.key) ? '（必填）' : ''}`"><el-select v-if="isGenderKey(field.key)" :model-value="genderText(member.values[field.key])" placeholder="未识别" clearable @update:model-value="v => member.values[field.key] = v ?? ''"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select><el-input v-else :model-value="String(member.values[field.key] ?? '')" @update:model-value="v => member.values[field.key] = v" /></el-form-item></div></article></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'HOUSEHOLD_REGISTER'" v-model="openPanels"><el-collapse-item id="rev-new-members" title="补录遗漏成员" name="new-members"><p>成员字段按当前必填设置填写，原件页必须指定；全户完整性仍需逐页覆盖确认。</p><article v-for="(member,index) in addedMembers" :key="index" class="edit-row"><el-form-item label="新增成员原件页"><el-input-number v-model="member.source_page" :min="1" :max="pageCount" :precision="0"/></el-form-item><div class="field-grid"><el-form-item v-for="(label,key) in memberLabels" :key="key" :class="{ 'field-missing': addedMemberMissing(member, key) }" :label="`${label}${memberFieldRequired(result, key) ? '（必填）' : ''}`"><el-input :model-value="String(member.fields[key] ?? '')" @update:model-value="v => member.fields[key] = v"/></el-form-item></div><el-button @click="addedMembers.splice(index,1)">撤销新增成员</el-button></article><el-button @click="addedMembers.push({fields:{},source_page:1})">新增成员</el-button></el-collapse-item></el-collapse><template v-if="result.doc_type === 'GENERIC'"><h4 id="rev-generic" data-guide="generic-edit">通用全文与键值{{ result.required_field_keys?.includes('generic.full_text') ?? true ? '（正文必填）' : '（正文选填）' }}</h4><el-input v-model="generic.full_text" type="textarea" :rows="6" :class="{ 'field-missing': genericFullTextRequired && !generic.full_text }" /><div v-for="(pair,index) in generic.key_values" :key="index" class="generic-row"><el-input v-model="pair.key" placeholder="字段名"/><el-input v-model="pair.value" type="textarea" autosize placeholder="字段值（原文为空可留空）"/><el-button v-if="genericPairSource(result,pair)" @click="emit('locate',genericPairSource(result,pair)!)">原始来源</el-button><el-button link type="danger" @click="removePair(index)">删除</el-button></div><el-button @click="generic.key_values.push({key:'',value:''})">新增键值</el-button></template>
      <el-collapse v-model="openPanels"><el-collapse-item id="rev-coverage" title="全页覆盖确认（仅实际逐页核对后填写）" name="coverage"><el-checkbox v-model="coverageEnabled">我已逐页检查原件及遗漏内容</el-checkbox><template v-if="coverageEnabled"><p>原始材料共 {{ pageCount || '未知' }} 页；未知总页数时不能提交完整覆盖声明。</p><el-checkbox-group v-model="checkedPages"><el-checkbox v-for="page in pageCount" :key="page" :value="page">第 {{ page }} 页</el-checkbox></el-checkbox-group><el-input v-model="coverageReason" placeholder="说明人工补齐与完整性核对依据" type="textarea"/><article v-for="region in regions ?? []" :key="region.region_id" class="edit-row"><span>第 {{ region.page }} 页区域 {{ region.region_id.slice(0,8) }}</span><el-select v-model="regionActions[region.region_id]" clearable placeholder="未补充覆盖声明"><el-option value="TRANSCRIBED" label="已补录"/><el-option value="NO_CONTENT" label="已确认无业务文字"/></el-select><el-input v-if="regionActions[region.region_id]" v-model="regionReasons[region.region_id]" placeholder="该区域核对理由"/><el-select v-if="regionActions[region.region_id] === 'TRANSCRIBED'" v-model="regionItems[region.region_id]" multiple placeholder="对应已存在项目"><el-option v-for="item in result.items ?? []" :key="item.item_id" :label="item.name" :value="item.item_id"/></el-select><template v-if="regionActions[region.region_id] === 'TRANSCRIBED'"><el-select v-model="regionFields[region.region_id]" multiple placeholder="本次补录字段"><el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key"/></el-select><el-select v-model="regionAdded[region.region_id]" multiple placeholder="本次新增检测项目"><el-option v-for="(item,index) in added" :key="index" :label="item.name || `新增 ${index+1}`" :value="index"/></el-select><el-select v-model="regionFindings[region.region_id]" multiple placeholder="本次修正清单"><el-option v-for="(f,index) in findings" :key="f.finding_id" :label="`清单 ${index+1}`" :value="f.finding_id"/></el-select><el-select v-model="regionMembers[region.region_id]" multiple placeholder="本次修正成员"><el-option v-for="(_,index) in members" :key="index" :label="`成员 ${index+1}`" :value="index"/></el-select><el-select v-if="result.doc_type === 'HOUSEHOLD_REGISTER'" v-model="regionAddedMembers[region.region_id]" multiple placeholder="本次新增成员"><el-option v-for="(member,index) in addedMembers" :key="index" :value="index" :label="String(member.fields.name || `新增成员 ${index+1}`)"/></el-select><el-checkbox v-if="result.doc_type === 'GENERIC'" v-model="regionGeneric[region.region_id]">本次补录通用全文</el-checkbox></template></article></template></el-collapse-item></el-collapse>
      <el-alert v-if="message" type="warning" :closable="false">{{ message }}</el-alert>
      <el-button data-guide="review-save" type="primary" :loading="busy" :disabled="!canWrite" @click="save">保存修正并重新校验</el-button>
    </el-form>
  </section>
</template>
<style scoped>
.number-length-hint { width:100%; margin:6px 0 0; color:var(--el-color-danger); line-height:1.5; }
.number-length-hint.info { color:var(--el-text-color-secondary); }
/* 字段级异议就地红字，与结果表格、顶部红字三处呼应。 */
.field-issue { margin:6px 0 0; color:var(--el-color-danger); line-height:1.5; }
.review-editor { margin-top:20px; }
/* 人工核对与修正：框内讲解文字和数据输入整体加粗，与框外说明拉开层次。 */
.review-editor { font-weight: 600; }
.review-editor :deep(.el-input__inner), .review-editor :deep(.el-textarea__inner), .review-editor :deep(.el-select__wrapper) { font-weight: 600; }
.field-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px; } .edit-row,.issue-row { border:1px solid var(--el-border-color);padding:12px;margin:10px 0;border-radius:6px; } .generic-row { display:flex;gap:8px;margin:8px 0; } .el-select { margin:5px 0; } .issue-row .el-checkbox { display:block; } @media(max-width:750px){.field-grid{grid-template-columns:1fr}}
/* 缺失必填：红边 + 浅红底一眼定位；填上值立即恢复普通样式。 */
.field-missing :deep(.el-input__wrapper), .field-missing :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; background-color: var(--el-color-danger-light-9); }
.field-missing :deep(.el-textarea__inner) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; background-color: var(--el-color-danger-light-9); }
.field-missing :deep(.el-form-item__label) { color: var(--el-color-danger); }
/* 红字跳转定位后的短暂高亮；减少动态偏好下不动画，只滚动到位。 */
.jump-flash { animation: jump-flash 1.5s ease 1; }
@keyframes jump-flash { 0%, 100% { box-shadow: none; } 30%, 70% { box-shadow: 0 0 0 3px var(--el-color-warning-light-5); } }
@media (prefers-reduced-motion: reduce) { .jump-flash { animation: none; } }
.bank-candidates { width: 100%; min-width: 0; margin-top: 6px; display: grid; gap: 6px; }
/* 候选采用行：与识别字段表格的候选提示条同族（浅黄底 + 图标）；原因小字常规字重，候选值加粗，操作右置。 */
.candidate-pick { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; padding: 6px 10px; border-radius: 6px; background: var(--el-color-warning-light-9); }
.candidate-pick .candidate-icon { color: var(--el-color-warning); flex-shrink: 0; }
.candidate-pick .candidate-body { flex: 1; min-width: 0; display: grid; gap: 2px; justify-items: start; }
.candidate-pick .candidate-reason { font-size: 12px; font-weight: 400; line-height: 1.5; color: var(--el-text-color-secondary); }
.candidate-pick .candidate-value { font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
</style>
