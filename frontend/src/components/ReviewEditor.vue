<script setup lang="ts">
import { householdMemberLabels as memberLabels } from '../business.ts'
import { memberFieldRequired } from '../requiredFields.ts'
import { computed, reactive, ref, watch } from 'vue'
import { genderText, isGenderKey, isMedicalReviewItem, medicalProjectCount } from '../business.ts'
import type { DocProfile, FieldSource, TaskResult } from '../business.ts'
import { addedMember, buildReview, canAcceptIssue, changedValues, collectIssues, looksMasked, memberFields, summaryPatch } from '../review.ts'
import type { AbsenceReason, ReviewBody, Scalar } from '../review.ts'
const props = defineProps<{ result: TaskResult; profile?: DocProfile; canWrite: boolean; busy: boolean; pageCount: number; regions?: { region_id: string; page: number }[] }>()
const emit = defineEmits<{ (e: 'save', body: ReviewBody): void; (e: 'dirty', value: boolean): void; (e: 'locate', source: FieldSource): void }>()
const fields = computed(() => props.result.fields ?? Object.values(props.result.basic_info ?? {}))
const values = reactive<Record<string, Scalar>>(Object.fromEntries(fields.value.map(f => [f.key, f.value])))
const absence = reactive<Record<string, AbsenceReason | ''>>({})
const projectCount = computed(() => medicalProjectCount(values.exam_projects))
const editable = (key: string) => (props.profile?.fields.find(f => f.key === key)?.editable ?? fields.value.find(f => f.key === key)?.editable) !== false
const itemKeys = ['name', 'alias', 'category', 'result_raw', 'unit', 'reference_range', 'reported_abnormal_marker', 'risk_grade', 'diagnosis'] as const
const itemLabels: Record<string, string> = { name: '项目名称', alias: '别名', category: '类别', result_raw: '检测结果原文', unit: '单位', reference_range: '参考范围', reported_abnormal_marker: '报告标记', risk_grade: '报告等级', diagnosis: '异常诊断' }
const reviewItems = computed(() => (props.result.items ?? []).filter(isMedicalReviewItem))
const items = reactive(reviewItems.value.map(i => ({ item_id: i.item_id, values: Object.fromEntries(itemKeys.map(k => [k, i[k] ?? ''])), absence: {} as Record<string, AbsenceReason | ''>, removed: false })))
const added = ref<Record<string, string>[]>([])
const findings = reactive((props.result.report_summary?.findings ?? []).map(f => ({ finding_id: f.finding_id, values: { text: f.text, risk_grade: f.risk_grade ?? '', diagnosis: f.diagnosis ?? '' }, removed: false, result_item_id: undefined as string | null | undefined, absence: {} as Record<string, AbsenceReason | ''> })))
const members = reactive((props.result.members ?? []).map(m => ({ values: Object.fromEntries(memberFields(m).map(f => [f.key, f.value])) as Record<string, Scalar>, absence: {} as Record<string, AbsenceReason | ''>, removed: false })))
const addedMembers = ref<{fields:Record<string,Scalar>;source_page:number}[]>([])
const originalGeneric = props.result.reviewed_generic ?? props.result.generic
const generic = reactive({ full_text: originalGeneric?.full_text ?? '', key_values: (originalGeneric?.key_values ?? []).map(k => ({ key: k.key, value: k.value })) })
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
const genericFullTextRequired = computed(() => props.result.required_field_keys?.includes('generic.full_text') ?? true)
function setField(key: string, value: string) { const kind=props.profile?.fields.find(f=>f.key===key)?.type; values[key]=value===''?null:kind==='integer'||kind==='number'?Number(value):kind==='boolean'?value==='true':value }
const fieldKind = (key: string) => props.profile?.fields.find(f=>f.key===key)?.type
const absenceObject = (source: Record<string, AbsenceReason | ''>) => Object.fromEntries(Object.entries(source).filter(([, v]) => v)) as Record<string, AbsenceReason>
watch([values, absence, items, added, findings, members, generic, coverageEnabled, checkedPages, coverageReason, regionActions, regionReasons, regionItems, regionFields, regionAdded, regionFindings, regionMembers, regionGeneric, summaryEnabled, summaryReason, summaryPage, summaryCount, addedFindings], () => emit('dirty', true), { deep: true })
function save() {
  message.value = ''
  try {
    const body = buildReview(props.result, { fields: values, absence_reasons: absenceObject(absence), accepted_issues: issues.value.filter(row => canAcceptIssue(row.issue)).map(row => ({ issue_id: row.issue.issue_id })) })
    body.items = items.filter(i => !i.removed).flatMap(i => {
      const old = props.result.items!.find(o => o.item_id === i.item_id)!
      const changed = changedValues(old as unknown as Record<string, unknown>, i.values)
      if (Object.hasOwn(changed, 'result_raw')) changed.result_raw = i.values.result_raw
      const abs = absenceObject(i.absence)
      return Object.keys(changed).length || Object.keys(abs).length ? [{ item_id: i.item_id, ...changed, ...(Object.keys(abs).length ? { absence_reasons: abs } : {}) }] : []
    })
    body.removed_item_ids = items.filter(i => i.removed).map(i => i.item_id)
    body.added_items = added.value.map(item => {
      if (!item.name?.trim() || !item.result_raw?.trim() || Object.values(item).some(looksMasked)) throw new Error('INVALID_ITEM')
      return { ...item }
    })
    body.findings = findings.filter(f=>!f.removed).flatMap(f => {
      const old = props.result.report_summary!.findings.find(o => o.finding_id === f.finding_id)!
      const change = changedValues(old as unknown as Record<string, unknown>, f.values)
      const abs = absenceObject(f.absence)
      if (f.result_item_id !== undefined) change.result_item_id = f.result_item_id || null
      return Object.keys(change).length || Object.keys(abs).length ? [{ finding_id: f.finding_id, ...change, ...(Object.keys(abs).length ? { absence_reasons: abs } : {}) }] : []
    })
    body.members = members.flatMap((m, index) => {
      if(m.removed) return []
      const original = Object.fromEntries(memberFields(props.result.members![index]!).map(f => [f.key, f.value]))
      const change = changedValues(original, m.values) as Record<string, Scalar>, abs = absenceObject(m.absence)
      for (const key of Object.keys(abs)) {
        if (Object.hasOwn(change, key) && change[key] !== null) throw new Error('CONFLICTING_ABSENCE')
        delete change[key]
      }
      return Object.keys(change).length || Object.keys(abs).length ? [{ index, fields: change, absence_reasons: abs }] : []
    })
    body.removed_member_indexes = members.flatMap((member,index)=>member.removed?[index]:[])
    body.added_members = addedMembers.value.map(member=>addedMember(member.fields,member.source_page,props.pageCount,Object.keys(memberLabels).filter(key=>memberFieldRequired(props.result,key))))
    if (props.result.doc_type === 'GENERIC' && JSON.stringify(generic) !== JSON.stringify({ full_text: originalGeneric?.full_text ?? '', key_values: originalGeneric?.key_values.map(k => ({ key: k.key, value: k.value })) ?? [] })) {
      if (looksMasked(generic.full_text) || generic.key_values.some(k => looksMasked(k.value))) throw new Error('MASKED_VALUE')
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
    message.value = error instanceof Error && error.message === 'MASKED_VALUE' ? '不能把掩码当作原始值提交。未改的掩码将跳过；需修正时请查看原件并输入完整值。' : '请检查：新增项目需名称和结果；覆盖确认需逐页勾选及理由。'
  }
}
</script>
<template>
  <section class="review-editor">
    <h3>人工核对与修正</h3>
    <p v-if="result.doc_type === 'MEDICAL_REPORT'" class="conf">体检项目数量由“本次体检项目意义”的大项清单计数；修正下方体检项目清单即可更新。身高、体重可作为台账字段修正，仍不计异常；小结只作结论证据，BMI照常核对。</p>
    <el-alert type="info" :closable="false">只提交实际修改的业务字段，原始识别证据保留。可确认的核对问题会在保存时自动确认；掩码不是原始值，置信度不会因人工确认提高。必填缺值和冲突须修正。</el-alert>
    <el-form label-position="top" :disabled="!canWrite || busy">
      <div class="field-grid">
        <el-form-item v-for="field in fields" :key="field.key" :class="{ 'field-missing': missingRequired(field.key) }" :label="`${field.label}${required(field.key) ? '（必填）' : ''}`">
          <el-select v-if="fieldKind(field.key) === 'boolean'" v-model="values[field.key]"><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select>
          <el-select v-else-if="isGenderKey(field.key)" :model-value="genderText(values[field.key])" placeholder="未识别" clearable @update:model-value="v => setField(field.key, v ?? '')"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select>
          <el-input v-else :type="['exam_projects','blood_routine','urine_routine','ecg','dr_imaging','abdominal_ultrasound','liver_function'].includes(field.key) ? 'textarea' : 'text'" :rows="3" :model-value="String((field.key === 'exam_project_count' ? projectCount : values[field.key]) ?? '')" :disabled="!editable(field.key)" @update:model-value="v => setField(field.key,v)" />
          <el-select v-if="!required(field.key) && editable(field.key)" v-model="absence[field.key]" placeholder="缺省原因（可选）" clearable><el-option label="原件未记载" value="NOT_ON_DOCUMENT" /><el-option label="不适用" value="NOT_APPLICABLE" /></el-select>
          <el-button v-if="result.doc_type === 'MEDICAL_REPORT'" link @click="emit('locate', field.source ?? {})">查看来源 / 整页</el-button>
        </el-form-item>
      </div>
      <el-collapse v-if="items.length || result.doc_type === 'MEDICAL_REPORT'">
        <el-collapse-item title="编辑检测项目 / 增删项目" name="items">
          <article v-for="(item, index) in items" :key="item.item_id" class="edit-row">
            <el-checkbox v-model="item.removed">删除该项目（提交后生效）</el-checkbox>
            <div v-if="!item.removed" class="field-grid"><el-form-item v-for="key in itemKeys" :key="key" :label="itemLabels[key]"><el-input v-model="item.values[key]" /></el-form-item></div>
            <div v-if="!item.removed" class="field-grid"><el-select v-for="key in ['risk_grade','diagnosis']" :key="key" v-model="item.absence[key]" :placeholder="`${itemLabels[key]}缺省原因`" clearable><el-option label="原件未记载" value="NOT_ON_DOCUMENT" /><el-option label="不适用" value="NOT_APPLICABLE" /></el-select></div>
            <el-button link @click="emit('locate', reviewItems[index]?.source ?? {})">检测行来源</el-button>
            <el-button v-for="(source, si) in reviewItems[index]?.diagnosis_sources ?? []" :key="si" link @click="emit('locate', source)">诊断来源 {{ si + 1 }}</el-button>
          </article>
          <article v-for="(item, index) in added" :key="index" class="edit-row"><div class="field-grid"><el-form-item v-for="key in itemKeys" :key="key" :label="itemLabels[key]"><el-input v-model="item[key]" /></el-form-item></div><el-button @click="added.splice(index,1)">撤销新增</el-button></article>
          <el-button @click="added.push(Object.fromEntries(itemKeys.map(k => [k,''])))">新增检测项目</el-button>
        </el-collapse-item>
      </el-collapse>
      <el-collapse v-if="findings.length"><el-collapse-item title="编辑报告检查治疗清单" name="findings"><article v-for="(finding,index) in findings" :key="finding.finding_id" class="edit-row">
        <el-checkbox v-model="finding.removed">删除此清单条目（需下方清单修正理由与来源页）</el-checkbox>
        <el-form-item label="报告条目原文"><el-input v-model="finding.values.text" type="textarea" /></el-form-item>
        <div class="field-grid"><el-form-item label="报告等级"><el-input v-model="finding.values.risk_grade" /></el-form-item><el-form-item label="异常诊断"><el-input v-model="finding.values.diagnosis" /></el-form-item></div>
        <el-select v-model="finding.result_item_id" placeholder="检测结果关联保持不变"><el-option label="取消关联" :value="''" /><el-option v-for="item in result.items ?? []" :key="item.item_id" :value="item.item_id" :label="`${item.name} · ${item.result_raw}`" /></el-select>
        <el-select v-for="key in ['risk_grade','diagnosis','result_raw']" :key="key" v-model="finding.absence[key]" :placeholder="`${itemLabels[key]}缺省原因`" clearable><el-option label="原件未记载" value="NOT_ON_DOCUMENT" /><el-option label="不适用" value="NOT_APPLICABLE" /></el-select>
        <el-button v-for="(source,si) in result.report_summary?.findings[index]?.sources ?? []" :key="si" link @click="emit('locate',source)">清单来源 {{ si + 1 }}</el-button>
      </article></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'MEDICAL_REPORT'"><el-collapse-item title="清单声明数 / 增删条目" name="summary-edit"><el-checkbox v-model="summaryEnabled">修正报告清单（不影响实验室计数）</el-checkbox><template v-if="summaryEnabled"><el-select v-model="summaryScope" aria-label="清单作用域"><el-option label="需检查治疗清单" value="follow_up_required"/><el-option label="总检结论" value="overall_conclusion"/><el-option label="未识别" value="unidentified"/></el-select><el-input v-model="summaryTitle" placeholder="原报告清单标题（改声明数量或作用域时必填）"/><el-form-item label="原件明确声明数量；未声明留空，不用条目长度代填"><el-input-number :disabled="summaryScope !== 'follow_up_required'" v-model="summaryCount" :min="0" :precision="0" /></el-form-item><el-form-item label="声明或清单所在原件页"><el-input-number v-model="summaryPage" :min="1" :max="pageCount" :precision="0" /></el-form-item><el-input v-model="summaryReason" placeholder="说明修正的原件依据（必填）"/><article v-for="(f,index) in addedFindings" :key="index" class="edit-row"><el-input v-model="f.text" placeholder="清单条目原文"/><el-input v-model="f.risk_grade" placeholder="报告等级"/><el-input v-model="f.diagnosis" placeholder="异常诊断"/><el-select v-model="f.result_item_id" clearable placeholder="关联检测项目"><el-option v-for="item in result.items ?? []" :key="item.item_id" :label="item.name" :value="item.item_id"/></el-select><el-button @click="addedFindings.splice(index,1)">撤销新增</el-button></article><el-button @click="addedFindings.push({text:'',risk_grade:'',diagnosis:''})">新增清单条目</el-button></template></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'HOUSEHOLD_REGISTER'"><el-collapse-item title="户口本成员" name="members"><article v-for="(member,index) in members" :key="index" class="edit-row"><h4>成员 {{ index + 1 }}</h4><el-checkbox v-model="member.removed">删除此成员（提交后生效）</el-checkbox><div v-if="!member.removed" class="field-grid"><el-form-item v-for="field in memberFields(result.members![index]!)" :key="field.key" :class="{ 'field-missing': memberMissing(member, field.key) }" :label="`${field.label}${memberFieldRequired(result, field.key) ? '（必填）' : ''}`"><el-select v-if="isGenderKey(field.key)" :model-value="genderText(member.values[field.key])" placeholder="未识别" clearable @update:model-value="v => member.values[field.key] = v ?? ''"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select><el-input v-else :model-value="String(member.values[field.key] ?? '')" @update:model-value="v => member.values[field.key] = v" /><el-select v-if="!memberFieldRequired(result, field.key)" v-model="member.absence[field.key]" placeholder="缺省原因" clearable><el-option label="原件未记载" value="NOT_ON_DOCUMENT"/><el-option label="不适用" value="NOT_APPLICABLE"/></el-select></el-form-item></div></article></el-collapse-item></el-collapse>
      <el-collapse v-if="result.doc_type === 'HOUSEHOLD_REGISTER'"><el-collapse-item title="补录遗漏成员" name="new-members"><p>成员字段按当前必填设置填写，原件页必须指定；全户完整性仍需逐页覆盖确认。</p><article v-for="(member,index) in addedMembers" :key="index" class="edit-row"><el-form-item label="新增成员原件页"><el-input-number v-model="member.source_page" :min="1" :max="pageCount" :precision="0"/></el-form-item><div class="field-grid"><el-form-item v-for="(label,key) in memberLabels" :key="key" :class="{ 'field-missing': addedMemberMissing(member, key) }" :label="`${label}${memberFieldRequired(result, key) ? '（必填）' : ''}`"><el-input :model-value="String(member.fields[key] ?? '')" @update:model-value="v => member.fields[key] = v"/></el-form-item></div><el-button @click="addedMembers.splice(index,1)">撤销新增成员</el-button></article><el-button @click="addedMembers.push({fields:{},source_page:1})">新增成员</el-button></el-collapse-item></el-collapse><template v-if="result.doc_type === 'GENERIC'"><h4>通用全文与键值{{ result.required_field_keys?.includes('generic.full_text') ?? true ? '（正文必填）' : '（正文选填）' }}</h4><el-input v-model="generic.full_text" type="textarea" :rows="6" :class="{ 'field-missing': genericFullTextRequired && !generic.full_text }" /><div v-for="(pair,index) in generic.key_values" :key="index" class="generic-row"><el-input v-model="pair.key" placeholder="字段名"/><el-input v-model="pair.value" placeholder="字段值"/><el-button @click="generic.key_values.splice(index,1)">删除</el-button></div><el-button @click="generic.key_values.push({key:'',value:''})">新增键值</el-button></template>
      <el-collapse><el-collapse-item title="全页覆盖确认（仅实际逐页核对后填写）" name="coverage"><el-checkbox v-model="coverageEnabled">我已逐页检查原件及遗漏内容</el-checkbox><template v-if="coverageEnabled"><p>原始材料共 {{ pageCount || '未知' }} 页；未知总页数时不能提交完整覆盖声明。</p><el-checkbox-group v-model="checkedPages"><el-checkbox v-for="page in pageCount" :key="page" :value="page">第 {{ page }} 页</el-checkbox></el-checkbox-group><el-input v-model="coverageReason" placeholder="说明人工补齐与完整性核对依据" type="textarea"/><article v-for="region in regions ?? []" :key="region.region_id" class="edit-row"><span>第 {{ region.page }} 页区域 {{ region.region_id.slice(0,8) }}</span><el-select v-model="regionActions[region.region_id]" clearable placeholder="未补充覆盖声明"><el-option value="TRANSCRIBED" label="已补录"/><el-option value="NO_CONTENT" label="已确认无业务文字"/></el-select><el-input v-if="regionActions[region.region_id]" v-model="regionReasons[region.region_id]" placeholder="该区域核对理由"/><el-select v-if="regionActions[region.region_id] === 'TRANSCRIBED'" v-model="regionItems[region.region_id]" multiple placeholder="对应已存在项目"><el-option v-for="item in result.items ?? []" :key="item.item_id" :label="item.name" :value="item.item_id"/></el-select><template v-if="regionActions[region.region_id] === 'TRANSCRIBED'"><el-select v-model="regionFields[region.region_id]" multiple placeholder="本次补录字段"><el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key"/></el-select><el-select v-model="regionAdded[region.region_id]" multiple placeholder="本次新增检测项目"><el-option v-for="(item,index) in added" :key="index" :label="item.name || `新增 ${index+1}`" :value="index"/></el-select><el-select v-model="regionFindings[region.region_id]" multiple placeholder="本次修正清单"><el-option v-for="(f,index) in findings" :key="f.finding_id" :label="`清单 ${index+1}`" :value="f.finding_id"/></el-select><el-select v-model="regionMembers[region.region_id]" multiple placeholder="本次修正成员"><el-option v-for="(_,index) in members" :key="index" :label="`成员 ${index+1}`" :value="index"/></el-select><el-select v-if="result.doc_type === 'HOUSEHOLD_REGISTER'" v-model="regionAddedMembers[region.region_id]" multiple placeholder="本次新增成员"><el-option v-for="(member,index) in addedMembers" :key="index" :value="index" :label="String(member.fields.name || `新增成员 ${index+1}`)"/></el-select><el-checkbox v-if="result.doc_type === 'GENERIC'" v-model="regionGeneric[region.region_id]">本次补录通用全文</el-checkbox></template></article></template></el-collapse-item></el-collapse>
      <el-alert v-if="message" type="warning" :closable="false">{{ message }}</el-alert>
      <el-button type="primary" :loading="busy" :disabled="!canWrite" @click="save">保存修正并重新校验</el-button>
      <span class="conf">后端决定是否完成复核；提交成功不自动代表可导出。</span>
    </el-form>
  </section>
</template>
<style scoped>
.review-editor { margin-top:20px; } .field-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px; } .edit-row,.issue-row { border:1px solid var(--el-border-color);padding:12px;margin:10px 0;border-radius:6px; } .generic-row { display:flex;gap:8px;margin:8px 0; } .el-select { margin:5px 0; } .issue-row .el-checkbox { display:block; } @media(max-width:750px){.field-grid{grid-template-columns:1fr}}
/* 缺失必填：红边 + 浅红底一眼定位；填上值立即恢复普通样式。 */
.field-missing :deep(.el-input__wrapper), .field-missing :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; background-color: var(--el-color-danger-light-9); }
.field-missing :deep(.el-textarea__inner) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; background-color: var(--el-color-danger-light-9); }
.field-missing :deep(.el-form-item__label) { color: var(--el-color-danger); }
</style>
