<script setup lang="ts">
import { computed, reactive, ref, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleClose, Delete, RefreshRight, UploadFilled, User, View, WarningFilled } from '@element-plus/icons-vue'
import ExportControls from './ExportControls.vue'
import UploadPanel from './UploadPanel.vue'
import PersonNameEditor from './PersonNameEditor.vue'
import OperationGuide from './OperationGuide.vue'
import type { BusinessApi } from '../api.ts'
import { ApiFailure, shouldRefreshResult, isAbort } from '../api.ts'
import { batchLabels, docTypes, pairingLabels, isPersonPackage, hasResult, hasMissingRequiredFields, requiredFieldLabels, hasExportDisputes, disputedFieldLabels, runningStatuses, taskLabels } from '../business.ts'
import type { Batch, BatchStatus, DocProfile, IdCardPairing, Task, TaskStatus } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import { entryNeedsReview, entryRunning } from '../monitor.ts'
import type { BatchEntry, Monitor } from '../monitor.ts'
import { batchOwnerLabel, expiryText, fairQueueHint, formatTime, sortBatchTasks, taskProgressView } from '../presentation.ts'
import { groupBatchEntries, periodBounds, rangeSuffix } from '../batchCalendar.ts'
import type { BatchPeriod } from '../batchCalendar.ts'

const props = defineProps<{ monitor: Monitor; canWrite: boolean; isAdmin: boolean; api: BusinessApi | null; uploadReset: number; catalogue: DocProfile[]; active?: boolean }>()
const emit = defineEmits<{
  (e: 'open-result', task: Task, batchId: string): void
  (e: 'unauthorized'): void
  (e: 'batch-deleted', batchId: string, taskIds: string[]): void
  (e: 'task-deleted', batchId: string, taskId: string): void
  (e: 'preview', files: File[], tasks: Task[]): void
}>()

const selected = reactive<Record<string, Task[]>>({})
const missingOnly = reactive<Record<string, boolean>>({})
const disputedOnly = reactive<Record<string, boolean>>({})
const loadingMore = ref(false)
const acting = ref('')
const appendTarget = ref<Batch | null>(null)
let moreController: AbortController | undefined
let actionController: AbortController | undefined
let disposed = false
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
onUnmounted(() => { disposed = true; moreController?.abort(); actionController?.abort() })

// Keyed by the id from monitor.order, not entry.batch, so optimistic entries
// (batch still null right after upload) keep a stable identity too.
const entries = computed(() => props.monitor.state.listedIds
  .map(id => ({ id, entry: props.monitor.state.entries[id] }))
  .filter((item): item is { id: string; entry: BatchEntry } => item.entry !== undefined))
const groups = computed(() => groupBatchEntries(entries.value, period.value))
const hasQueuedTasks = computed(() => entries.value.some(({ entry }) => entry.tasks.some(task => task.status === 'QUEUED')))
const missingTasks = computed(() => Object.fromEntries(entries.value.map(({ id, entry }) => [id, entry.tasks.filter(hasMissingRequiredFields)])))
const disputedTasks = computed(() => Object.fromEntries(entries.value.map(({ id, entry }) => [id, entry.tasks.filter(hasExportDisputes)])))
const orderedTasks = computed(() => Object.fromEntries(entries.value.map(({ id, entry }) => [id, sortBatchTasks(entry.tasks)])))
// Number the complete batch before filtering so a file keeps its reference number.
const taskNumbers = computed(() => Object.fromEntries(Object.values(orderedTasks.value)
  .flatMap(tasks => tasks.map((task, index) => [task.task_id, index + 1]))))
const visibleTasks = (id: string) => (orderedTasks.value[id] ?? []).filter(t =>
  !missingOnly[id] && !disputedOnly[id] || !!missingOnly[id] && hasMissingRequiredFields(t) || !!disputedOnly[id] && hasExportDisputes(t))
const isTableEntry = (entry: BatchEntry) => entry.tasks.some(task => task.doc_type === 'TABLE')

const expandedNames = computed<string[]>({
  get: () => props.monitor.state.order.filter(id => props.monitor.state.entries[id]?.expanded),
  set: names => { props.monitor.state.listedIds.forEach(id => props.monitor.setExpanded(id, names.includes(id))) },
})

const taskTagTypes: Record<TaskStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  QUEUED: 'info', PREPROCESSING: 'primary', OCR: 'primary', EXTRACTING: 'primary', VALIDATING: 'primary',
  NEED_REVIEW: 'warning', COMPLETED: 'success', FAILED: 'danger', REJECTED: 'info', CANCELLED: 'info',
}
const batchTagTypes: Record<BatchStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  PROCESSING: 'primary', COMPLETED: 'success', PARTIAL: 'warning', FAILED: 'danger', CANCELLED: 'info',
}
// 身份证两面配套状态：齐全为成功，缺人像面为警告，未指定/缺国徽面（可选）保持中性。
const pairingTagTypes: Record<IdCardPairing, 'success' | 'warning' | 'info'> = {
  unassigned: 'info', not_provided: 'info', missing_front: 'warning', missing_back: 'info', both_present: 'success',
}

// 未命名批次回退显示创建时间（分钟精度可区分同日多批）；uuid 前缀对操作员无意义且几乎无法区分。
function batchTitle(batchId: string) {
  const batch = props.monitor.state.entries[batchId]?.batch
  if (batch?.display_name) return batch.display_name
  const stamp = batch?.created_at ? formatTime(batch.created_at) : ''
  return stamp !== '' && stamp !== '—' ? `未命名批次 ${stamp.slice(0, 16)}` : '未命名批次'
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
  const expiry = expiryText(batch?.expires_at)
  if (expiry) parts.push(expiry)
  return parts.join(' · ')
}

const progressViews = computed(() => Object.fromEntries(entries.value.flatMap(({ entry }) =>
  entry.tasks.map(task => [task.task_id, taskProgressView(task)]))))

async function changePage(page: number, size = props.monitor.state.pageSize) {
  if (loadingMore.value) return
  moreController = new AbortController()
  loadingMore.value = true
  try {
    await props.monitor.changePage(page, moreController.signal, size)
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
  if (disposed || acting.value) return
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

async function runRerun(batchId: string, task: Task) {
  if (disposed || acting.value || !canRerun(task)) return
  const version = { ...task }
  acting.value = `confirm-rerun:${task.task_id}`
  try {
    await ElMessageBox.confirm(`确认重跑「${task.file_name ?? '该文件'}」？重跑会清空当前显示的识别结果和人工修正。需要保留时，请先取消并导出当前结果；本页面暂不支持恢复历史版本。`, '重跑任务', {
      type: 'warning', confirmButtonText: '确认重跑', cancelButtonText: '取消',
    })
  } catch { return }
  finally { acting.value = '' }
  await doAction('rerun', batchId, version)
}

async function deleteBatch(batchId: string) {
  const entry = props.monitor.state.entries[batchId]
  if (!props.isAdmin || acting.value || !entry?.tasksLoaded || !entry.tasks.length || entryRunning(entry)) return
  // Freeze the versions shown when confirmation opens, not the later poll snapshot.
  const tasks = entry.tasks.map(task => ({ ...task }))
  acting.value = `delete:${batchId}`
  try {
    await ElMessageBox.confirm(`确认永久删除「${batchTitle(batchId)}」及其中 ${tasks.length} 个任务？服务器保存的原文件、识别结果和处理历史会一起删除，无法恢复。电脑上的原始素材不受影响。`, '删除批次', {
      type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '取消',
    })
  } catch { acting.value = ''; return }
  actionController = new AbortController()
  try {
    const result = await props.monitor.deleteBatch(batchId, tasks, actionController.signal)
    delete selected[batchId]
    delete missingOnly[batchId]
    emit('batch-deleted', batchId, result.task_ids)
    if (result.cleanup_pending) ElMessage.warning('批次记录已删除，但部分文件暂未清理；请联系维护人员重启服务完成清理。')
    else ElMessage.success('批次及其识别文件、结果已删除。')
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) emit('unauthorized')
      else if (shouldRefreshResult(error) || error.card.http_status === 404) {
        props.monitor.start()
        ElMessage.warning('批次已变化或不存在，未执行本次删除；请刷新核对后再操作。')
      } else ElMessage.error(errorMessages[error.card.code])
    } else ElMessage.error(errorMessages.UNKNOWN_ERROR)
  } finally { acting.value = '' }
}

async function deleteTask(batchId: string, task: Task) {
  if (!props.canWrite || acting.value || runningStatuses.has(task.status)) return
  const version = { ...task }
  acting.value = `delete-task:${task.task_id}`
  try {
    await ElMessageBox.confirm(`确认永久删除「${task.file_name ?? '该文件'}」？服务器保存的该文件、识别结果和处理历史会一起删除，无法恢复。其他任务不受影响；删除最后一个任务后空批次也会移除。`, '删除任务', {
      type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '取消',
    })
  } catch { acting.value = ''; return }
  if (disposed) { acting.value = ''; return }
  actionController = new AbortController()
  try {
    const result = await props.monitor.deleteTask(batchId, version, actionController.signal)
    if (disposed || actionController.signal.aborted) return
    selected[batchId] = (selected[batchId] ?? []).filter(item => item.task_id !== task.task_id)
    if (result.batch_deleted) {
      delete selected[batchId]
      delete missingOnly[batchId]
      delete disputedOnly[batchId]
    }
    emit('task-deleted', batchId, task.task_id)
    if (result.cleanup_pending) ElMessage.warning('任务记录已删除，但部分文件暂未清理；请联系维护人员重启服务完成清理。')
    else ElMessage.success('任务及其识别文件、结果已删除。')
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) emit('unauthorized')
      else if (shouldRefreshResult(error) || error.card.http_status === 404 || error.card.code === 'INVALID_STATE') {
        props.monitor.start()
        ElMessage.warning('任务已变化或不存在，未执行本次删除；请刷新核对后再操作。')
      } else ElMessage.error(errorMessages[error.card.code])
    } else ElMessage.error(errorMessages.UNKNOWN_ERROR)
  } finally { acting.value = '' }
}

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

// 两个筛选互斥：点选其一清除另一个，再点一次取消，回到显示全部。
function setMissingOnly(batchId: string, value: boolean) {
  missingOnly[batchId] = value
  if (value) disputedOnly[batchId] = false
}
function setDisputedOnly(batchId: string, value: boolean) {
  disputedOnly[batchId] = value
  if (value) missingOnly[batchId] = false
}
// 删除批次的禁用原因：不可用时悬停可见，可用时不占版面（后果在确认框里交代）。
const deleteBlockReason = (entry: BatchEntry) => entryRunning(entry)
  ? '请等待排队及识别任务停止后再删除。'
  : !entry.tasksLoaded ? '正在获取任务，稍后可删除。'
    : !entry.tasks.length ? '本批次没有可删除的任务。' : ''
</script>

<template>
  <section class="batch-board">
    <div class="calendar-toolbar">
      <span>按时间分组</span>
      <span class="calendar-controls" data-guide="batch-calendar">
        <el-radio-group v-model="period" aria-label="批次时间分组">
          <el-radio-button value="day">日</el-radio-button>
          <el-radio-button value="week">周</el-radio-button>
          <el-radio-button value="month">月</el-radio-button>
        </el-radio-group>
        <el-date-picker v-model="anchor" :key="period" :type="period === 'day' ? 'date' : period"
          value-format="YYYY-MM-DD" :format="period === 'month' ? 'YYYY年MM月' : period === 'week' ? 'YYYY-MM-DD [所在周]' : 'YYYY-MM-DD'"
          :placeholder="period === 'day' ? '选择日期' : period === 'week' ? '选择周' : '选择月份'" clearable />
        <!-- 阅读顺序：先当前范围括注，再「全部日期」清除动作；括注的周语义由 rangeSuffix 按视图给出。 -->
        <span class="poll-hint">{{ dateRange ? `${dateRange.date_from} 至 ${dateRange.date_to}` : '全部日期' }}{{ rangeSuffix(period, !!dateRange) }}</span>
        <el-button v-if="anchor" link type="primary" @click="anchor = null">全部日期</el-button>
      </span>
    </div>
    <div class="board-toolbar">
      <el-tag v-if="monitor.state.polling" type="success" effect="plain" round>自动刷新中 · 每 2 秒</el-tag>
      <el-tag v-else-if="monitor.state.lastCheckedAt" type="info" effect="plain" round>暂无进行中的任务，已停止轮询</el-tag>
      <span v-if="monitor.state.lastCheckedAt" class="poll-hint">上次检查 {{ formatTime(monitor.state.lastCheckedAt) }}</span>
      <div class="toolbar-spacer" />
      <span class="board-actions" data-guide="batch-refresh">
        <el-button :icon="RefreshRight" @click="monitor.start()">刷新</el-button>
      </span>
    </div>

    <el-alert
      v-if="monitor.state.retrying"
      class="retry-alert"
      type="warning"
      :closable="false"
      show-icon
      :title="`与服务连接中断，正在自动重试（第 ${monitor.state.failureCount} 次，间隔逐次加长）…`"
    />

    <div data-guide="batch-list" class="guide-batch-hint">展开批次查看文件、导出检查与本批次指引。</div>
    <p v-if="hasQueuedTasks" class="guide-batch-hint">{{ fairQueueHint }}将鼠标移到“处理进度”可查看入队和实际开始时间。</p>
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
            <el-tag v-if="entry.tasksLoaded && missingTasks[id]?.length" size="small" type="danger" effect="light">{{ missingTasks[id]?.length }} 个任务缺必填</el-tag>
            <el-tag v-else-if="!entry.tasksLoaded" size="small" type="info" effect="plain">必填检查中</el-tag>
            <el-tag v-if="entry.tasksLoaded && disputedTasks[id]?.length" size="small" type="warning" effect="light">{{ disputedTasks[id]?.length }} 个任务有异议</el-tag>
            <span class="batch-meta">{{ batchMeta(id) }}</span>
            <span v-if="entry.batch" class="batch-meta batch-owner">上传人：{{ batchOwnerLabel(entry.batch.owner) }}</span>
          </span>
        </template>

        <div :data-guide-scope="`batch-${id}`">
        <div class="batch-actions">
          <ExportControls :api="api" :tasks="entry.tasks" :selected="entry.tasks.filter(t => (selected[id] ?? []).some(s => s.task_id === t.task_id))" :batch-id="id" :batch="entry.batch ?? undefined" :can-write="canWrite" @unauthorized="emit('unauthorized')" />
          <OperationGuide label="本批次指引" :context="entry.batch && isPersonPackage(entry.batch) ? 'package' : 'batch'" :scope="`batch-${id}`" :can-write="canWrite" :is-admin="isAdmin" :active="active !== false && expandedNames.includes(id) && !appendTarget" />
          <el-tooltip v-if="isAdmin" placement="top" :disabled="!deleteBlockReason(entry)" :content="deleteBlockReason(entry)">
            <span>
              <el-button type="danger" plain :icon="Delete" :loading="acting === `delete:${id}`" :disabled="!!acting || !!deleteBlockReason(entry)" @click="deleteBatch(id)">删除批次</el-button>
            </span>
          </el-tooltip>
        </div>
        <PersonNameEditor v-if="entry.batch && isPersonPackage(entry.batch)" :batch="entry.batch" :monitor="monitor" :can-write="canWrite" @unauthorized="emit('unauthorized')" />
        <div v-if="entry.batch && isPersonPackage(entry.batch)" class="package-toolbar" data-guide="package-pairing" :class="{ 'has-warning': entry.batch.warnings?.length }">
          <el-icon class="package-icon"><User /></el-icon>
          <el-tag size="small" :type="pairingTagTypes[entry.batch.id_card_pairing ?? 'not_provided']" effect="light">{{ pairingLabels[entry.batch.id_card_pairing ?? 'not_provided'] }}</el-tag>
          <span class="poll-hint">配套仅检查两面材料是否存在；请人工核对归属，不影响必填导出条件。</span>
          <span class="toolbar-spacer" />
          <el-button v-if="canWrite" data-guide="package-append" type="primary" plain :icon="UploadFilled" @click="appendTarget = { ...entry.batch }">补充上传</el-button>
        </div>
        <div class="required-toolbar">
          <span class="filter-checks" data-guide="batch-filter">
            <el-check-tag v-if="entry.tasksLoaded" class="tag-missing" :checked="!!missingOnly[id]" @change="value => setMissingOnly(id, value)">{{ isTableEntry(entry) ? '只看导出待处理' : '只看必填未填' }}（{{ missingTasks[id]?.length ?? 0 }}）</el-check-tag>
            <el-check-tag v-if="entry.tasksLoaded && !isTableEntry(entry)" class="tag-disputed" :checked="!!disputedOnly[id]" @change="value => setDisputedOnly(id, value)">只看有异议（{{ disputedTasks[id]?.length ?? 0 }}）</el-check-tag>
          </span>
          <span v-if="!entry.tasksLoaded" class="poll-hint">正在获取任务，检查必填信息…</span>
          <span class="poll-hint">{{ isTableEntry(entry) ? '完整表格可直接导出；有修改时才需保存。' : '补齐并保存后标记自动更新；' }}筛选不改变“本批次全部”的导出范围。</span>
        </div>
        <p data-guide="batch-tasks" class="guide-batch-hint">文件按文件名自然排序；筛选后保留原序号。点击文件行或操作列中的按钮查看识别结果。</p>
        <el-table :data="visibleTasks(id)" row-key="task_id" :row-class-name="({ row }) => hasMissingRequiredFields(row as Task) || hasExportDisputes(row as Task) ? 'required-missing-row' : ''" @selection-change="rows => selected[id] = rows" @row-click="row => onRowClick(id, row)">
          <template #empty>{{ missingOnly[id] || disputedOnly[id] ? '本批次没有符合筛选条件的任务' : entry.tasksLoaded ? '暂无任务' : '正在获取任务…' }}</template>
          <el-table-column type="selection" width="45" :reserve-selection="true" />
          <el-table-column label="序号" width="65" align="center">
            <template #default="{ row }">{{ taskNumbers[row.task_id] }}</template>
          </el-table-column>
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
          <el-table-column label="导出检查" min-width="220">
            <template #default="{ row }">
              <span v-if="runningStatuses.has(row.status)" class="poll-hint">识别中，尚未检查</span>
              <template v-else-if="hasMissingRequiredFields(row as Task) || hasExportDisputes(row as Task)"><div v-if="hasMissingRequiredFields(row as Task)" class="required-fields-cell">
                <el-tag size="small" type="danger" effect="light">{{ row.doc_type === 'TABLE' ? '导出待处理' : '必填未填' }}</el-tag>
                <span class="missing-field-names">{{ requiredFieldLabels(row as Task, catalogue).join('、') || '请打开结果查看缺失项' }}</span>
              </div>
              <div v-if="hasExportDisputes(row as Task)" class="required-fields-cell">
                <el-tag size="small" type="warning" effect="light">有异议</el-tag>
                <span class="missing-field-names">{{ disputedFieldLabels(row as Task, catalogue).join('、') }}</span>
              </div></template>
              <el-tag v-else-if="row.export_ready === true" size="small" type="success" effect="plain">{{ row.doc_type === 'TABLE' ? '可直接导出' : '必填已齐' }}</el-tag>
              <span v-else-if="row.export_blockers?.some((blocker: { field: string }) => ['task', 'doc_type'].includes(blocker.field))" class="poll-hint">暂无识别结果</span>
              <span v-else class="poll-hint">尚未检查</span>
            </template>
          </el-table-column>
          <el-table-column label="处理进度" width="235">
            <template #default="{ row }">
              <el-tooltip v-if="progressViews[row.task_id]" placement="top" :disabled="!progressViews[row.task_id]!.tooltip" :content="progressViews[row.task_id]!.tooltip">
                <div class="task-progress">
                  <div class="task-progress__label">
                    <span v-if="progressViews[row.task_id]!.active" class="rainbow-spinner task-progress__spin" aria-hidden="true"></span>
                    <span>{{ progressViews[row.task_id]!.label }}</span>
                  </div>
                  <el-progress v-if="progressViews[row.task_id]!.percentage !== null"
                    :percentage="progressViews[row.task_id]!.percentage!" :show-text="false" :stroke-width="6"
                    :status="progressViews[row.task_id]!.incomplete > 0 ? 'warning' : undefined" aria-label="图像识别区域处理量" />
                  <div v-if="progressViews[row.task_id]!.amount" class="task-progress__amount">{{ progressViews[row.task_id]!.amount }}</div>
                  <div v-if="progressViews[row.task_id]!.incomplete > 0" class="task-progress__warning">{{ progressViews[row.task_id]!.incomplete }} 个区域不完整，请核对</div>
                </div>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="255" align="left">
            <template #default="{ row }">
              <el-button v-if="hasResult(row as Task)" link type="primary" :icon="View" @click.stop="openResult(row as Task, id)">{{ canWrite && hasMissingRequiredFields(row as Task) ? '补填' : canWrite && hasExportDisputes(row as Task) ? '核对' : '查看' }}</el-button>
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
              <el-button v-if="canWrite" link type="danger" :icon="Delete"
                :loading="acting === `delete-task:${row.task_id}`"
                :disabled="!!acting || runningStatuses.has(row.status)"
                :title="runningStatuses.has(row.status) ? '请先取消任务，等待识别停止后再删除' : '删除该任务'"
                @click.stop="deleteTask(id, row as Task)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </el-collapse-item>
      </section>
    </el-collapse>
    <!-- 空列表（含筛选后 serverTotal 为 0）不显示分页器；有记录才给翻页入口。 -->
    <el-pagination v-if="monitor.state.serverTotal > 0" background :current-page="monitor.state.page" :page-size="monitor.state.pageSize" :total="monitor.state.serverTotal"
      :page-sizes="[20, 50, 100]" :disabled="loadingMore || !!acting" layout="total, sizes, prev, pager, next, jumper" class="list-pager"
      @update:current-page="changePage($event)" @update:page-size="changePage(1, $event)" />
    <el-dialog :model-value="!!appendTarget" title="补充人员材料" width="min(1000px, 94vw)" destroy-on-close @close="appendTarget = null" @closed="monitor.start()">
      <UploadPanel v-if="appendTarget" :target-batch="appendTarget" :api="api" :catalogue="catalogue" :monitor="monitor" :can-write="canWrite" @submitted="appendTarget = null" @preview="(files, tasks) => emit('preview', files, tasks)" @unauthorized="emit('unauthorized')" />
    </el-dialog>
  </section>
</template>

<style scoped>
.guide-batch-hint { margin: 8px 16px; font-size: 13px; color: var(--el-text-color-secondary); }
.board-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.list-pager { justify-content: flex-end; flex-wrap: wrap; row-gap: 8px; margin-top: 16px; }
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
.required-toolbar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 0 16px 10px; }
/* 展开批次的首行操作区：导出控件靠左，本批次指引与删除批次靠右成一排。 */
.batch-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 16px 4px; }
/* 指引锚点的控件组包裹：框住具体控件而非整条工具栏。 */
.calendar-controls, .board-actions, .filter-checks { display: inline-flex; align-items: center; gap: 10px; flex-wrap: wrap; }
/* 筛选改为互斥的可点标签：选中即过滤，语义配色与任务行的必填/异议标记一致。 */
.filter-checks .el-check-tag { cursor: pointer; }
.filter-checks .el-check-tag.tag-missing.is-checked { background-color: var(--el-color-danger); color: #fff; }
.filter-checks .el-check-tag.tag-disputed.is-checked { background-color: var(--el-color-warning); border-color: var(--el-color-warning); color: #fff; }
.package-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0 16px 10px; padding: 10px 14px; background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-8); border-radius: 10px; }
.package-toolbar.has-warning { background: var(--el-color-warning-light-9); border-color: var(--el-color-warning-light-8); }
.package-icon { color: var(--el-color-primary); font-size: 16px; flex: none; }
.package-toolbar.has-warning .package-icon { color: var(--el-color-warning); }
.package-name { font-weight: 600; }
.required-fields-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.missing-field-names { font-size: 12px; color: var(--el-color-danger); word-break: break-word; }
.batch-collapse :deep(.required-missing-row) { --el-table-tr-bg-color: var(--el-color-danger-light-9); }
.task-progress { width: 100%; display: grid; gap: 5px; padding-block: 3px; font-size: 12px; line-height: 1.5; }
.task-progress__label { display: flex; align-items: center; gap: 6px; }
.task-progress__spin { width: 14px; height: 14px; --ring: 2.5px; flex: none; }
.task-progress__amount { color: var(--el-text-color-secondary); }
.task-progress__warning { color: var(--el-color-warning-dark-2); }
</style>
