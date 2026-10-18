<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Download, Search } from '@element-plus/icons-vue'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import { auditActor, auditFailure } from '../audit.ts'
import type { AuditFilters, AuditOptions, AuditOutcome, AuditRecord } from '../audit.ts'
import { formatTime } from '../presentation.ts'
import { errorMessages } from '../diagnostics.ts'

const props = defineProps<{ api: BusinessApi }>()
const emit = defineEmits<{ unauthorized: [] }>()
const options = ref<AuditOptions>({ actors: [], events: [], outcomes: [] })
const range = ref<[string, string] | null>(null), actor = ref(''), event = ref(''), outcome = ref<AuditOutcome | ''>(''), batch = ref('')
const rows = ref<AuditRecord[]>([])
const busy = ref(false), exporting = ref(false), error = ref('')
// 服务端数字分页：total/page/page_size 由后端按同一筛选快照给出；失败时保留当前页结果与页码。
const page = ref(1), pageSize = ref(50), total = ref(0)
let controller = new AbortController(), generation = 0
let applied: AuditFilters = {}
const filters = (): AuditFilters => ({ ...(range.value ? { date_from: range.value[0], date_to: range.value[1] } : {}),
  ...(actor.value ? { actor: actor.value } : {}), ...(event.value ? { event: event.value } : {}),
  ...(outcome.value ? { outcome: outcome.value } : {}), ...(batch.value.trim() ? { batch_id: batch.value.trim() } : {}) })
function failed(value: unknown) {
  if (value instanceof ApiFailure && value.card.http_status === 401) emit('unauthorized')
  return value instanceof ApiFailure ? errorMessages[value.card.code] : '操作审计读取失败，请稍后重试。'
}
async function fetchPage(target: number) {
  if (busy.value || exporting.value) return
  const revision = ++generation
  busy.value = true; error.value = ''
  try {
    const result = await props.api.auditPage(applied, target, pageSize.value, controller.signal)
    if (revision !== generation || controller.signal.aborted) return
    rows.value = result.items; total.value = result.total; page.value = result.page
  } catch (value) { if (revision === generation && !isAbort(value)) error.value = failed(value) }
  finally { if (revision === generation) busy.value = false }
}
function query() {
  if (busy.value || exporting.value) return
  applied = filters()
  void fetchPage(1)
}
function onPageChange(target: number) { void fetchPage(target) }
function onSizeChange(size: number) { pageSize.value = size; void fetchPage(1) }
async function download() {
  if (busy.value || exporting.value) return
  exporting.value = true; error.value = ''
  const revision = generation
  try {
    const blob = await props.api.auditExport(filters(), controller.signal)
    if (revision !== generation || controller.signal.aborted) return
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `操作审计_${new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()).replace(/[-: ]/g, '')}.xlsx`
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (value) { if (!controller.signal.aborted && !isAbort(value)) error.value = failed(value) }
  finally { if (!controller.signal.aborted) exporting.value = false }
}
onMounted(async () => {
  try {
    const result = await props.api.auditOptions(controller.signal)
    if (!controller.signal.aborted) { options.value = result; await fetchPage(1) }
  }
  catch (value) { if (!isAbort(value)) error.value = failed(value) }
})
onBeforeUnmount(() => { generation++; controller.abort(); rows.value = [] })
</script>

<template>
  <section class="audit-panel">
    <el-form class="filters" data-guide="audit-filter" @submit.prevent="query()">
      <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" class="range" />
      <el-select v-model="actor" clearable filterable placeholder="全部账号"><el-option v-for="item in options.actors" :key="item.id" :value="item.id" :label="item.username ? `${item.display_name}（${item.username}）` : item.display_name" /></el-select>
      <el-select v-model="event" clearable filterable placeholder="全部操作"><el-option v-for="item in options.events" :key="item.value" :value="item.value" :label="item.label" /></el-select>
      <el-select v-model="outcome" clearable placeholder="全部结果"><el-option v-for="item in options.outcomes" :key="item.value" :value="item.value" :label="item.label" /></el-select>
      <el-input v-model="batch" clearable placeholder="输入完整批次编号" class="batch" />
      <span class="filter-actions">
        <el-button type="primary" native-type="submit" :icon="Search" :loading="busy" :disabled="exporting">查询／回到首页</el-button>
        <el-button data-guide="audit-export" plain :icon="Download" :loading="exporting" :disabled="busy" @click="download">按筛选条件导出 Excel</el-button>
      </span>
    </el-form>
    <p class="hint">默认显示最近 7 天，时间为北京时间（UTC+8）；同一次提交的多份材料会合并为一条记录。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table :data="rows" v-loading="busy" stripe class="audit-list" data-guide="audit-list" :empty-text="error ? '当前无法确认查询结果' : '没有符合条件的操作记录'">
      <el-table-column label="时间（UTC+8）" width="175"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作者" min-width="190"><template #default="{ row }">{{ auditActor(row as AuditRecord) }}</template></el-table-column>
      <el-table-column prop="description" label="操作" min-width="260" />
      <el-table-column label="关联对象" min-width="210"><template #default="{ row }"><span class="identifier">{{ row.object_label || row.batch_id || row.target_id || '—' }}</span></template></el-table-column>
      <el-table-column label="结果" width="200"><template #default="{ row }"><el-tag size="small" effect="light" :type="row.outcome === 'failure' ? 'danger' : row.outcome === 'success' ? 'success' : 'info'">{{ row.outcome_label }}</el-tag><p v-if="row.outcome === 'failure'" class="failure-reason">{{ auditFailure(row as AuditRecord) }}</p></template></el-table-column>
    </el-table>
    <div class="footer">
      <span>导出包含全部匹配记录（最多 10000 条），不只当前页。</span>
      <el-pagination class="list-pager" background :current-page="page" :page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next, jumper" :disabled="busy || exporting"
        @current-change="onPageChange" @size-change="onSizeChange" />
    </div>
  </section>
</template>

<style scoped>
/* 筛选区：单行工具条（窄屏自动换行），占位符代替常驻标签；卡片底色与批次工具栏同风格。 */
.filters { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; background: var(--el-fill-color-lighter); border-radius: 10px; }
.filters :deep(.el-date-editor) { width: 280px; }
.filters .el-select { width: 168px; }
.filters .batch { width: 230px; }
/* 查询/导出按钮组：单行时靠右收尾，换行时自然成右对齐的第二行。 */
.filter-actions { display: inline-flex; align-items: center; gap: 10px; margin-left: auto; }
.hint { margin: 10px 0 12px; font-size: 12px; line-height: 1.7; color: var(--el-text-color-secondary); }
.failure-reason { margin: 4px 0 0; font-size: 12px; line-height: 1.5; color: var(--el-color-danger); overflow-wrap: anywhere; }
.identifier { overflow-wrap: anywhere; white-space: pre-wrap; }
.footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
.list-pager { justify-content: flex-end; }
</style>
