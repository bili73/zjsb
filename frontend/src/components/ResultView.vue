<script setup lang="ts">
import { computed, ref } from 'vue'
import { InfoFilled, Lock } from '@element-plus/icons-vue'
import { abnormalBasisLabels, fieldValueText, matchesMedicalFilter, medicalFlag } from '../business.ts'
import { canAcceptIssue } from '../review.ts'
import { numberLengthHint } from '../numberLength.ts'
import type { Field, FieldSource, ItemsFilter, MedicalItem, TaskResult } from '../business.ts'
import { searchMedicalItems } from '../workbench.ts'

const props = defineProps<{ result: TaskResult; filter: ItemsFilter }>()
const emit = defineEmits<{
  (e: 'locate', source: FieldSource): void
  (e: 'update:filter', value: ItemsFilter): void
}>()

const search = ref('')

const isMedical = computed(() => props.result.doc_type === 'MEDICAL_REPORT')
const certFields = computed<Field[]>(() => props.result.fields ?? Object.values(props.result.basic_info ?? {}))
const lengthHints = computed(() => Object.fromEntries(certFields.value.map(field => [field.key, numberLengthHint(props.result.doc_type, field.key, field.value)])))
const visibleItems = computed(() => searchMedicalItems((props.result.items ?? []).filter(item => matchesMedicalFilter(item, props.filter)), search.value))

const scopeLabels = { follow_up_required: '需随访/复检清单', overall_conclusion: '总体结论', unidentified: '未能识别的清单' } as const
const countCheckLabels = { match: '清单条目数吻合', mismatch: '清单条目数不符', unverified: '清单数量未核对' } as const

function fieldText(field: Field): string {
  return fieldValueText(field, isMedical.value)
}
// 不能一键确认的字段级异议（校验失败/冲突等）在字段行内就地提示，别让顶部红字成为唯一线索。
const fieldIssues = (field: Field) => (field.review_issues ?? []).filter(issue => !canAcceptIssue(issue))
function flagTone(item: MedicalItem): 'success' | 'danger' | 'warning' | 'info' {
  if (item.abnormal_exclusion_reason) return 'info'
  if (item.abnormal_basis === 'unknown') return 'warning'
  if (item.abnormal_flag === 'NORMAL') return 'success'
  if (item.abnormal_flag === 'UNKNOWN') return 'info'
  return 'danger'
}
function basisText(item: MedicalItem): string {
  if (item.abnormal_exclusion_reason === 'HEIGHT_WEIGHT') return '身高、体重保留原始结果，不纳入异常汇总、统计或人工复核；体重指数（BMI）照常判定和复核。'
  if (item.abnormal_exclusion_reason === 'SECTION_SUMMARY') return '小结是原文证据，不作为独立检测项目参与统计或人工复核。'
  const basis = `判定依据：${abnormalBasisLabels[item.abnormal_basis]}`
  return item.reported_abnormal_marker ? `${basis} · 报告标记「${item.reported_abnormal_marker}」` : basis
}
const statText = (value: number | null) => (value === null ? '未确认' : String(value))
function onFilterChange(value: string | number | boolean | undefined) { emit('update:filter', value as ItemsFilter) }
function locate(source: FieldSource | undefined) { if ((isMedical.value || ['BANK_CARD','INTERVIEW_FORM','HOUSEHOLD_REGISTER'].includes(props.result.doc_type)) && source) emit('locate', source) }
</script>

<template>
  <div class="result-view">
    <el-descriptions v-if="certFields.length" :column="2" border>
      <template #title><span data-guide="result-fields">{{ isMedical ? '体检台账字段' : '识别字段' }}</span></template>
      <el-descriptions-item v-for="field in certFields" :key="field.key" :label="field.label" :span="isMedical && ['exam_projects','blood_routine','urine_routine','ecg','dr_imaging','abdominal_ultrasound','liver_function'].includes(field.key) ? 2 : 1">
        <span class="field-line">
          <span class="field-value">
            {{ fieldText(field) }}
          </span>
          <el-button v-if="(isMedical || ['BANK_CARD','INTERVIEW_FORM'].includes(result.doc_type)) && field.source" link type="primary" size="small" @click="locate(field.source)">定位</el-button>
          <el-dropdown v-if="(isMedical || ['BANK_CARD','INTERVIEW_FORM'].includes(result.doc_type)) && field.sources?.length" @command="index => locate(field.sources?.[Number(index)])">
            <el-button link type="primary" size="small">{{ field.key === 'exam_projects' ? '各项目来源' : '相关来源' }}</el-button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item v-for="(source,index) in field.sources" :key="index" :command="index">第{{ source.page }}页 · {{ source.raw_text }}</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </span>
        <p v-if="lengthHints[field.key]" role="status" :class="['number-length-hint', lengthHints[field.key]?.level]">{{ lengthHints[field.key]?.message }}</p>
        <p v-for="issue in fieldIssues(field)" :key="issue.issue_id" role="status" class="field-issue">{{ issue.message }}</p>
        <div v-if="['BANK_CARD','INTERVIEW_FORM'].includes(result.doc_type) && field.candidates?.length">
          <div v-for="(candidate,index) in field.candidates" :key="index" class="candidate-hint">
            <el-icon class="candidate-icon"><InfoFilled /></el-icon>
            <span>{{ candidate.reason ?? '候选值' }}：{{ candidate.value }}
              <el-button v-if="candidate.source" link type="primary" @click="locate(candidate.source)">查看来源</el-button>
            </span>
          </div>
        </div>
      </el-descriptions-item>
    </el-descriptions>

    <template v-if="isMedical">
      <div v-if="result.stats" class="stat-cards">
        <div class="stat-card">
          <div class="stat-label">纳入统计的检测指标数</div>
          <div class="stat-value">{{ statText(result.stats.total) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">正常</div>
          <div class="stat-value">{{ statText(result.stats.normal) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">异常</div>
          <div class="stat-value stat-abnormal">{{ statText(result.stats.abnormal) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">待判定</div>
          <div class="stat-value">{{ statText(result.stats.unknown) }}</div>
        </div>
      </div>

      <div class="result-toolbar">
        <el-radio-group data-guide="medical-items" :model-value="filter" size="default" @update:model-value="onFilterChange">
          <el-radio-button value="all">全部项目</el-radio-button>
          <el-radio-button value="abnormal">仅异常</el-radio-button>
          <el-radio-button value="unknown">仅待判定</el-radio-button>
        </el-radio-group>
        <el-input v-model="search" placeholder="搜索项目名 / 别名 / 分类" clearable class="item-search" />
      </div>

      <el-table :data="visibleItems" row-key="item_id" :empty-text="search ? '当前筛选条件下没有项目' : '本报告未返回项目明细'">
        <el-table-column label="项目" min-width="170">
          <template #default="{ row }">
            <div>{{ row.name }}</div>
            <div v-if="row.alias" class="conf">{{ row.alias }}</div>
          </template>
        </el-table-column>
        <el-table-column label="结果" min-width="150">
          <template #default="{ row }">
            <div v-if="row.result_raw">{{ row.result_raw }}{{ row.unit ?? '' }}</div>
            <div v-else class="result-missing">未填写</div>
            <div v-if="row.reference_range" class="conf">参考区间 {{ row.reference_range }}</div>
          </template>
        </el-table-column>
        <el-table-column label="报告等级 / 诊断" min-width="170"><template #default="{ row }"><div v-if="row.risk_grade || row.diagnosis"><div v-if="row.risk_grade">{{ row.risk_grade }}</div><div v-if="row.diagnosis">{{ row.diagnosis }}</div></div><div v-else class="conf">—</div><el-button v-for="(s,index) in row.diagnosis_sources ?? []" :key="index" link type="primary" @click="locate(s)">诊断来源 {{ Number(index)+1 }}</el-button></template></el-table-column>
        <el-table-column label="判定" width="110">
          <template #default="{ row }">
            <el-tooltip :content="basisText(row as MedicalItem)" placement="top">
              <el-tag size="small" :type="flagTone(row as MedicalItem)" effect="light">{{ medicalFlag(row as MedicalItem) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="原图" width="80" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.source" link type="primary" size="small" @click="locate(row.source)">定位</el-button>
            <span v-else class="conf">—</span>
          </template>
        </el-table-column>
      </el-table>

      <template v-if="result.report_summary">
        <h3 class="section-title" data-guide="medical-summary">结论汇总 · {{ scopeLabels[result.report_summary.scope] }}</h3>
        <el-alert v-if="result.report_summary.scope === 'unidentified'" type="info" :closable="false" show-icon>
          报告中未发现可识别的结论性清单。
        </el-alert>
        <template v-else>
          <div class="summary-meta">
            <el-tag
              size="small"
              effect="plain"
              :type="result.report_summary.count_check === 'match' ? 'success' : result.report_summary.count_check === 'mismatch' ? 'danger' : 'info'"
            >
              报告声明 {{ result.report_summary.declared_count ?? '—' }} 项 · {{ countCheckLabels[result.report_summary.count_check] }}
            </el-tag>
          </div>
          <el-table :data="result.report_summary.findings" row-key="finding_id" size="small">
            <el-table-column label="编号" width="90">
              <template #default="{ row }">{{ row.reported_number ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="内容" min-width="240">
              <template #default="{ row }">
                <div>{{ row.text }}</div>
                <div v-if="row.risk_grade || row.diagnosis" class="conf">{{ [row.risk_grade, row.diagnosis].filter(Boolean).join(' · ') }}</div>
              </template>
            </el-table-column>
            <el-table-column label="对应检测结果" min-width="160">
              <template #default="{ row }">
                <div>{{ row.result_raw ?? '未关联检测结果' }}</div>
                <el-button v-for="(s,index) in row.result_sources ?? []" :key="index" link type="primary" size="small" @click="locate(s)">结果来源 {{ Number(index)+1 }}</el-button>
              </template>
            </el-table-column>
            <el-table-column label="原图" width="80" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.sources[0]" link type="primary" size="small" @click="locate(row.sources[0])">定位</el-button>
                <span v-else class="conf">—</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </template>

    <el-alert v-for="(text, index) in result.limitations ?? []" :key="index" type="info" :closable="false" show-icon class="limitation">
      {{ text }}
    </el-alert>
  </div>
</template>

<style scoped>
.number-length-hint { margin:6px 0 0; color:var(--el-color-danger); line-height:1.5; }
.number-length-hint.info { color:var(--el-text-color-secondary); }
/* 字段级异议与缺失结果：红色就地提示，与顶部红字呼应。 */
.field-issue { margin:6px 0 0; color:var(--el-color-danger); line-height:1.5; }
.result-missing { color:var(--el-color-danger); }
/* 候选提示：浅黄提示条（图标 + 文案 + 查看来源），和普通识别值一眼区分，比 el-alert 轻量。 */
.candidate-hint { display:flex; align-items:flex-start; gap:6px; margin-top:6px; padding:6px 10px; border-radius:6px; background:var(--el-color-warning-light-9); font-size:13px; line-height:1.6; }
.candidate-hint .candidate-icon { margin-top:4px; color:var(--el-color-warning); flex-shrink:0; }
.candidate-hint .el-button { vertical-align:baseline; }
.item-search { width: 240px; }
.mask-icon { vertical-align: -2px; margin-right: 4px; color: var(--el-text-color-secondary); }
.stat-abnormal { color: var(--el-color-danger); }
.summary-meta { margin: 8px 0; }
.limitation { margin-top: 12px; }
</style>
