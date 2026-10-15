<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import { errorMessages } from '../diagnostics.ts'
import { formatTime } from '../presentation.ts'
import { logLevels } from '../serverDiagnostics.ts'
import type { LogFilters, LogLevel, LogRecord, LogStatus } from '../serverDiagnostics.ts'

const props = defineProps<{ api: BusinessApi; open: boolean; status: LogStatus | null; statusError: string }>()
const emit = defineEmits<{ (e: 'unauthorized'): void; (e: 'refresh-status'): void }>()
const level = ref<LogLevel | ''>(''), range = ref<[string, string] | null>(null)
const errorId = ref(''), taskId = ref(''), error = ref(''), rows = ref<LogRecord[]>([])
const busy = ref(false), downloading = ref(false), cursor = ref<string | null>(null)
const incomplete = ref(false), skippedFiles = ref(0), skippedRecords = ref(0)
let controller = new AbortController(), generation = 0
let applied: LogFilters = {}
const filters = (): LogFilters => ({ ...(level.value ? { level: level.value } : {}),
  ...(range.value ? { date_from: range.value[0], date_to: range.value[1] } : {}),
  ...(errorId.value.trim() ? { error_id: errorId.value.trim() } : {}), ...(taskId.value.trim() ? { task_id: taskId.value.trim() } : {}) })
const problem = computed(() => !!props.statusError || !!props.status && (!props.status.recording_ok || props.status.backup_ok === false || props.status.scan_ok === false))
function fail(value: unknown) {
  if (isAbort(value)) return
  if (value instanceof ApiFailure) {
    if (value.card.http_status === 401) emit('unauthorized')
    error.value = errorMessages[value.card.code]
  } else error.value = '诊断信息读取失败，请使用离线收集脚本。'
}
async function query(next = false) {
  if (busy.value || downloading.value) return
  if (!next) { applied = filters(); rows.value = []; cursor.value = null; incomplete.value = false }
  busy.value = true; error.value = ''
  const revision = generation
  try {
    const page = await props.api.diagnosticEvents(applied, next ? cursor.value : null, controller.signal)
    if (revision !== generation) return
    rows.value = page.items; cursor.value = page.next_cursor
    incomplete.value = page.incomplete; skippedFiles.value = page.skipped_files; skippedRecords.value = page.skipped_records
  } catch (value) { if (revision === generation) fail(value) }
  finally { if (revision === generation) busy.value = false }
}
async function download() {
  downloading.value = true; error.value = ''
  const revision = generation
  try {
    const result = await props.api.diagnosticBundle(filters(), controller.signal)
    if (revision !== generation) return
    const url = URL.createObjectURL(result.blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = '诊断日志.zip'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    if (result.incomplete || result.truncated) ElMessage.warning([
      result.incomplete ? '部分日志损坏或无法读取，诊断包不完整，原文件已保留；请联系维护人员。' : '',
      result.truncated ? '日志超过单次下载上限，已下载部分内容；请缩小日期范围后重新下载。' : '',
    ].filter(Boolean).join(''))
    else ElMessage.success('诊断包已下载，可交给维护人员排查。')
  } catch (value) { if (revision === generation) fail(value) }
  finally { if (revision === generation) downloading.value = false }
}
const size = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MiB`
const tone = (value: LogLevel) => value === 'CRITICAL' || value === 'ERROR' ? 'danger' : value === 'WARNING' ? 'warning' : 'info'
watch(() => [props.open, props.api] as const, ([open]) => {
  generation++; controller.abort(); controller = new AbortController(); busy.value = false; downloading.value = false; rows.value = []; cursor.value = null; error.value = ''
  incomplete.value = false; skippedFiles.value = 0; skippedRecords.value = 0
  if (open) void query()
}, { immediate: true })
onBeforeUnmount(() => { generation++; controller.abort() })
</script>

<template>
  <section class="server-diagnostics">
    <el-alert v-if="problem" type="error" :closable="false" show-icon>
      <template v-if="statusError">{{ statusError }}。请检查服务连接；暂时不能确认日志和备份状态。</template>
      <template v-else>请处理：{{ !status?.recording_ok ? '日志写入失败；' : '' }}{{ status?.backup_ok === false ? '自动备份失败（原日志已保留）；' : '' }}{{ status?.scan_ok === false ? '历史日志读取失败；' : '' }}可先下载本页错误信息，或在服务器运行离线收集脚本。</template>
    </el-alert>
    <div class="status-grid" v-if="status">
      <div><span>日志记录</span><strong>{{ status.recording_ok ? '正常' : '写入异常' }}</strong></div>
      <div><span>近24小时错误记录</span><strong>{{ status.scan_ok ? status.error_count_24h : '尚未确认' }}</strong></div>
      <div><span>最近自动备份</span><strong>{{ status.last_backup_at ? formatTime(status.last_backup_at) : status.backup_ok === false ? '尚无成功备份' : '首次备份进行中' }}</strong></div>
      <div><span>自动备份状态</span><strong>{{ status.backup_ok === null ? '检查中' : status.backup_ok ? '正常' : '失败' }}</strong></div>
    </div>
    <p class="help-line">按北京时间查询。默认只记录 ERROR（错误）和 CRITICAL（严重故障），正常运行和一般提醒不再新增记录；历史低等级日志仍可查询。运行日志保留7天，压缩备份保留30天，与材料保留设置分开。</p>
    <p v-if="status" class="help-line">日志 {{ size(status.raw_bytes) }} / {{ size(status.raw_limit_bytes) }}；备份 {{ size(status.archive_bytes) }} / {{ size(status.archive_limit_bytes) }}。状态检查于 {{ status.last_check_at ? formatTime(status.last_check_at) : '检查中' }}。<el-button link @click="emit('refresh-status')">刷新状态</el-button></p>
    <el-form label-position="top" class="filters" @submit.prevent="query()">
      <el-form-item label="等级"><el-select v-model="level" clearable placeholder="全部等级（含历史）"><el-option v-for="item in logLevels" :key="item" :label="item" :value="item" /></el-select></el-form-item>
      <el-form-item label="日期范围（最多31天）"><el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></el-form-item>
      <el-form-item label="错误 / 请求编号"><el-input v-model="errorId" clearable placeholder="粘贴错误编号或请求编号" /></el-form-item>
      <el-form-item label="任务编号"><el-input v-model="taskId" clearable placeholder="粘贴任务 UUID" /></el-form-item>
      <div class="actions"><el-button type="primary" native-type="submit" :loading="busy" :disabled="downloading">查询</el-button><el-button :loading="downloading" :disabled="busy" @click="download">下载诊断包</el-button></div>
    </el-form>
    <el-alert v-if="error" type="error" :closable="false" show-icon>{{ error }}</el-alert>
    <el-alert v-if="incomplete" type="warning" :closable="false" show-icon>日志结果不完整：扫描时跳过 {{ skippedFiles }} 个无法读取的文件和 {{ skippedRecords }} 条损坏记录，原文件已保留。下表仅展示可读取的匹配记录，不能据此判断没有其他错误；请联系维护人员。</el-alert>
    <el-table :data="rows" v-loading="busy" stripe border empty-text="没有符合条件的日志" class="log-table">
      <el-table-column type="expand"><template #default="{ row }"><div class="log-description"><strong>问题说明：</strong>{{ row.description }}</div><pre class="log-details">{{ JSON.stringify(row, null, 2) }}</pre></template></el-table-column>
      <el-table-column label="时间（UTC+8）" min-width="175"><template #default="{ row }">{{ formatTime(row.timestamp) }}</template></el-table-column>
      <el-table-column label="等级" width="110"><template #default="{ row }"><el-tag :type="tone(row.level)" size="small">{{ row.level }}</el-tag></template></el-table-column>
      <el-table-column prop="description" label="问题说明" min-width="300" />
      <el-table-column prop="component" label="模块" width="100" />
      <el-table-column prop="event" label="技术事件" min-width="180" />
      <el-table-column label="错误码 / 操作" min-width="180"><template #default="{ row }">{{ row.context.error_code || row.context.operation || '—' }}</template></el-table-column>
    </el-table>
    <div class="page-footer"><span>每页50条，按时间降序。展开左侧箭头查看错误编号、任务、阶段、耗时和代码位置；旧日志程序版本显示 unknown。</span><el-button v-if="cursor" :disabled="busy || downloading" @click="query(true)">下一页</el-button></div>
  </section>
</template>

<style scoped>
.server-diagnostics { margin-bottom: 28px; }
.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.status-grid > div { display: flex; flex-direction: column; gap: 8px; padding: 14px; background: var(--el-fill-color-light); border-radius: 8px; }
.status-grid span, .help-line, .page-footer { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.filters { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(300px, 2fr); gap: 0 16px; }
.filters :deep(.el-date-editor) { width: 100%; }
.actions { grid-column: 1 / -1; margin-bottom: 16px; }
.page-footer { display: flex; gap: 12px; justify-content: space-between; margin-top: 12px; }
.log-description { margin: 16px; line-height: 1.7; overflow-wrap: anywhere; }
.log-details { white-space: pre-wrap; overflow-wrap: anywhere; margin: 16px; max-height: 400px; overflow: auto; font-size: 12px; }
@media (max-width: 700px) { .filters, .status-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
