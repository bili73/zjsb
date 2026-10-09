<script setup lang="ts">
import { computed, reactive, ref, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleClose, RefreshRight, View, WarningFilled } from '@element-plus/icons-vue'
import ExportControls from './ExportControls.vue'
import type { BusinessApi } from '../api.ts'
import { ApiFailure, shouldRefreshResult, isAbort } from '../api.ts'
import { batchLabels, docTypes, hasResult, runningStatuses, taskLabels } from '../business.ts'
import type { BatchStatus, Task, TaskStatus } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import { entryNeedsReview, entryRunning } from '../monitor.ts'
import type { BatchEntry, Monitor } from '../monitor.ts'
import { formatTime } from '../presentation.ts'
import { groupBatchEntries, periodBounds } from '../batchCalendar.ts'
import type { BatchPeriod } from '../batchCalendar.ts'

const props = defineProps<{ monitor: Monitor; canWrite: boolean; api: BusinessApi | null; uploadReset: number }>()
const emit = defineEmits<{
  (e: 'open-result', task: Task, batchId: string): void
  (e: 'unauthorized'): void
}>()

const selected = reactive<Record<string, Task[]>>({})
const loadingMore = ref(false)
const acting = ref('')
let moreController: AbortController | undefined
let actionController: AbortController | undefined
const period = ref<BatchPeriod>('day')
const today = () => formatTime(new Date().toISOString()).slice(0, 10)
const anchor = ref<string | null>(today())
const dateRange = computed(() => periodBounds(anchor.value, period.value))
watch(dateRange, range => { moreController?.abort(); props.monitor.setDateRange(range) }, { immediate: true })
watch(() => props.uploadReset, () => {
  anchor.value = today()
  props.monitor.setDateRange(periodBounds(anchor.value, period.value))
})
watch(() => props.monitor.state.dateRange, range => { if (!range) anchor.value = null })
onUnmounted(() => { moreController?.abort(); actionController?.abort() })

// Keyed by the id from monitor.order, not entry.batch, so optimistic entries
// (batch still null right after upload) keep a stable identity too.
const entries = computed(() => props.monitor.state.order
  .filter(id => !props.monitor.state.dateRange || props.monitor.state.listedIds.includes(id))
  .map(id => ({ id, entry: props.monitor.state.entries[id] }))
  .filter((item): item is { id: string; entry: BatchEntry } => item.entry !== undefined))
const groups = computed(() => groupBatchEntries(entries.value, period.value))
const hasMore = computed(() => props.monitor.state.listedIds.length < props.monitor.state.serverTotal)

const expandedNames = computed<string[]>({
  get: () => props.monitor.state.order.filter(id => props.monitor.state.entries[id]?.expanded),
  set: names => { props.monitor.state.order.forEach(id => props.monitor.setExpanded(id, names.includes(id))) },
})

const taskTagTypes: Record<TaskStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  QUEUED: 'info', PREPROCESSING: 'primary', OCR: 'primary', EXTRACTING: 'primary', VALIDATING: 'primary',
  NEED_REVIEW: 'warning', COMPLETED: 'success', FAILED: 'danger', REJECTED: 'info', CANCELLED: 'info',
}
const batchTagTypes: Record<BatchStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  PROCESSING: 'primary', COMPLETED: 'success', PARTIAL: 'warning', FAILED: 'danger', CANCELLED: 'info',
}

function batchTitle(batchId: string) {
  return props.monitor.state.entries[batchId]?.batch?.display_name || `批次 ${batchId.slice(0, 8)}`
}

function batchMeta(batchId: string) {
  const entry = props.monitor.state.entries[batchId]
  if (!entry) return ''
  const batch = entry.batch
  const parts = [`${batch?.file_count ?? entry.tasks.length} 个文件`]
  if (batch?.need_review_count) parts.push(`待核对 ${batch.need_review_count}`)
  if (batch?.failed_count) parts.push(`失败 ${batch.failed_count}`)
  if (entryRunning(entry)) parts.push('执行中')
  parts.push(`创建于 ${formatTime(batch?.created_at)}（UTC+8）`)
  return parts.join(' · ')
}

async function loadMore() {
  if (loadingMore.value) return
  moreController = new AbortController()
  loadingMore.value = true
  try {
    await props.monitor.loadMore(moreController.signal)
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) emit('unauthorized')
      else ElMessage.error(errorMessages[error.card.code])
    } else {
      ElMessage.error(errorMessages.UNKNOWN_ERROR)
    }
  } finally {
    loadingMore.value = false
  }
}

async function doAction(operation: 'cancel' | 'rerun', batchId: string, task: Task) {
  if (acting.value) return
  actionController = new AbortController()
  acting.value = `${operation}:${task.task_id}`
  try {
    await props.monitor.runAction(operation, batchId, task, actionController.signal)
    if (operation === 'rerun') ElMessage.success('已提交重跑，新执行正在排队。')
  } catch (error) {
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) { emit('unauthorized'); return }
      if (shouldRefreshResult(error)) {
        props.monitor.start()
        ElMessage.info(errorMessages[error.card.code])
        return
      }
      ElMessage.error(errorMessages[error.card.code])
    } else {
      ElMessage.error(errorMessages.UNKNOWN_ERROR)
    }
  } finally {
    acting.value = ''
  }
}

async function runCancel(batchId: string, task: Task) {
  try {
    await ElMessageBox.confirm(`确认取消「${task.file_name ?? '该文件'}」的识别任务？取消后不再执行。`, '取消任务', {
      type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '再想想',
    })
  } catch { return }
  await doAction('cancel', batchId, task)
}

function runRerun(batchId: string, task: Task) { void doAction('rerun', batchId, task) }

function onRowClick(batchId: string, row: unknown) {
  const task = row as Task
  if (hasResult(task)) emit('open-result', task, batchId)
}
function openResult(task: Task, batchId: string) { emit('open-result', task, batchId) }

function errorTip(task: Task): string {
  const error = task.error
  if (!error) return ''
  return `${errorMessages[error.code]}${error.error_id ? `（错误编号 ${error.error_id}）` : ''}`
}

const canCancel = (task: Task) => props.canWrite && runningStatuses.has(task.status) && !task.cancel_requested
const canRerun = (task: Task) => props.canWrite && !runningStatuses.has(task.status)
</script>

<template>
  <section class="batch-board">
    <div class="calendar-toolbar">
      <span>按时间分组</span>
      <el-radio-group v-model="period" aria-label="批次时间分组">
        <el-radio-button value="day">日</el-radio-button>
        <el-radio-button value="week">周</el-radio-button>
        <el-radio-button value="month">月</el-radio-button>
      </el-radio-group>
      <el-date-picker v-model="anchor" :key="period" :type="period === 'day' ? 'date' : period"
        value-format="YYYY-MM-DD" :format="period === 'month' ? 'YYYY年MM月' : period === 'week' ? 'YYYY-MM-DD [所在周]' : 'YYYY-MM-DD'"
        :placeholder="period === 'day' ? '选择日期' : period === 'week' ? '选择周' : '选择月份'" clearable />
      <el-button v-if="anchor" link type="primary" @click="anchor = null">全部日期</el-button>
      <span class="poll-hint">{{ dateRange ? `${dateRange.date_from} 至 ${dateRange.date_to}` : '全部日期' }}（UTC+8，周一至周日）</span>
    </div>
    <div class="board-toolbar">
      <el-tag v-if="monitor.state.polling" type="success" effect="plain" round>自动刷新中 · 每 2 秒</el-tag>
      <el-tag v-else-if="monitor.state.lastCheckedAt" type="info" effect="plain" round>暂无进行中的任务，已停止轮询</el-tag>
      <span v-if="monitor.state.lastCheckedAt" class="poll-hint">上次检查 {{ formatTime(monitor.state.lastCheckedAt) }}</span>
      <div class="toolbar-spacer" />
      <el-button :icon="RefreshRight" @click="monitor.start()">刷新</el-button>
      <el-button v-if="hasMore" :loading="loadingMore" @click="loadMore">加载更早的批次</el-button>
    </div>

    <el-alert
      v-if="monitor.state.retrying"
      class="retry-alert"
      type="warning"
      :closable="false"
      show-icon
      :title="`与服务连接中断，正在自动重试（第 ${monitor.state.failureCount} 次，间隔逐次加长）…`"
    />

    <el-empty v-if="entries.length === 0" :description="anchor ? '该时间段暂无批次，可更换日期或查看全部日期。' : '暂无批次；切换到「上传识别」提交第一批文件。'" />

    <el-collapse v-else v-model="expandedNames" class="batch-collapse">
      <section v-for="group in groups" :key="group.key" class="batch-time-group">
        <h3 class="group-heading">{{ group.label }} <span>{{ group.entries.length }} 个批次</span></h3>
      <el-collapse-item v-for="{ id, entry } in group.entries" :key="id" :name="id">
        <template #title>
          <span class="batch-title">
            <span class="batch-name">{{ entry.batch ? batchTitle(id) : '新批次 · 创建中' }}</span>
            <el-tag size="small" :type="entry.batch ? batchTagTypes[entry.batch.status] : 'info'" effect="light">
              {{ entry.batch ? batchLabels[entry.batch.status] : '已提交' }}
            </el-tag>
            <el-tag v-if="entryNeedsReview(entry)" size="small" type="warning" effect="plain">有待核对</el-tag>
            <span class="batch-meta">{{ batchMeta(id) }}</span>
          </span>
        </template>

        <ExportControls :api="api" :tasks="entry.tasks" :selected="entry.tasks.filter(t => (selected[id] ?? []).some(s => s.task_id === t.task_id))" :batch-id="id" :can-write="canWrite" @unauthorized="emit('unauthorized')" />
        <el-table :data="entry.tasks" row-key="task_id" @selection-change="rows => selected[id] = rows" @row-click="row => onRowClick(id, row)">
          <el-table-column type="selection" width="45" />
          <el-table-column label="文件" min-width="220">
            <template #default="{ row }">
              <div class="file-cell">
                <span>{{ row.file_name ?? '（未提供文件名）' }}</span>
                <span v-if="monitor.pendingNotice(row.task_id)" class="pending-note">{{ monitor.pendingNotice(row.task_id) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ row.doc_type ? docTypes[row.doc_type as keyof typeof docTypes] ?? row.doc_type : '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="150">
            <template #default="{ row }">
              <span class="status-cell">
                <el-tag size="small" :type="taskTagTypes[row.status as TaskStatus]" effect="light">{{ taskLabels[row.status as TaskStatus] }}</el-tag>
                <el-tooltip v-if="row.error" placement="top" :content="errorTip(row as Task)">
                  <el-icon class="status-warn"><WarningFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="170">
            <template #default="{ row }">
              <el-progress v-if="runningStatuses.has(row.status)" :percentage="row.progress ?? 0" :stroke-width="6" />
              <span v-else class="poll-hint">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="210" align="left">
            <template #default="{ row }">
              <el-button v-if="hasResult(row as Task)" link type="primary" :icon="View" @click.stop="openResult(row as Task, id)">查看</el-button>
              <el-button
                v-if="canCancel(row as Task)"
                link
                type="danger"
                :icon="CircleClose"
                :loading="acting === `cancel:${row.task_id}`"
                @click.stop="runCancel(id, row as Task)"
              >取消</el-button>
              <el-tag v-else-if="row.cancel_requested && runningStatuses.has(row.status)" size="small" type="info" effect="plain">取消中</el-tag>
              <el-button
                v-if="canRerun(row as Task)"
                link
                type="primary"
                :icon="RefreshRight"
                :loading="acting === `rerun:${row.task_id}`"
                @click.stop="runRerun(id, row as Task)"
              >重跑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
      </section>
    </el-collapse>
  </section>
</template>

<style scoped>
.board-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.calendar-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.group-heading { margin: 0; padding: 12px 16px; font-size: 14px; background: var(--el-fill-color-light); }
.group-heading span { margin-left: 12px; font-size: 12px; font-weight: normal; color: var(--el-text-color-secondary); }
.toolbar-spacer { flex: 1; }
.retry-alert { margin-bottom: 12px; }
.batch-collapse { background: #fff; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; }
.batch-collapse :deep(.el-collapse-item__header) { padding: 0 16px; }
.batch-collapse :deep(.el-collapse-item__content) { padding-bottom: 8px; padding-top: 4px; }
.batch-collapse :deep(.el-table) { cursor: default; }
.status-cell { display: inline-flex; align-items: center; gap: 6px; }
.status-warn { color: var(--el-color-danger); }
</style>
