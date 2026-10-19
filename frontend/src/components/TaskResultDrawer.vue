<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { ApiFailure, isAbort, resultConflictAction } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import { resultKey } from '../business.ts'
import type { DocProfile, ItemsFilter, Task, TaskResult, FieldSource } from '../business.ts'
import type { ReviewBody } from '../review.ts'
import { canAcceptIssue, collectIssues, downloadBlob, exportBlockReason, spreadsheetName } from '../review.ts'
import type { IssueJump } from '../review.ts'
import { errorMessages } from '../diagnostics.ts'
import type { ErrorCode } from '../diagnostics.ts'
import type { LocalPreviewBatch } from '../workbench.ts'
import ResultView from './ResultView.vue'
import SourcePreview from './SourcePreview.vue'
import ReviewEditor from './ReviewEditor.vue'
import TableReview from './TableReview.vue'
import GenericSources from './GenericSources.vue'
import OperationGuide from './OperationGuide.vue'
import { detailGuideContext } from '../guide.ts'
import BankCardRecovery from './BankCardRecovery.vue'
import { needsBankCrop } from '../bankCrop.ts'
import { sourceSelection } from '../sourceLocation.ts'
import { isInteractiveClickTarget } from '../interactiveTarget.ts'
import type { Monitor } from '../monitor.ts'

const props = defineProps<{ open: boolean; task: Task | null; api: BusinessApi | null; monitor: Monitor; previews: LocalPreviewBatch; canWrite: boolean; catalogue: DocProfile[] }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'unauthorized'): void; (e: 'reviewed', task: Task): void; (e: 'bank-retried'): void; (e: 'preview', files: File[], tasks: Task[]): void }>()

const result = ref<TaskResult | null>(null)
const loading = ref(false)
const failed = ref<{ code: ErrorCode; error_id: string | null } | null>(null)
const filter = ref<ItemsFilter>('all')
const activeSource = ref<FieldSource | null>(null)
const refreshedOnce = ref(false)
const dirty = ref(false), saving = ref(false), stale = ref(false), reviewError = ref('')
let saveController: AbortController | undefined
let controller: AbortController | undefined
let disposed = false

const taskKey = computed(() => (props.task ? resultKey(props.task) : ''))
const isMedicalTask = computed(() => props.task?.doc_type === 'MEDICAL_REPORT')
const preview = computed(() => (props.task ? props.previews.get(props.task.task_id) : undefined))

async function fetchResult() {
  const task = props.task
  if (!props.open || !props.api || !task) return
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  failed.value = null
  try {
    const fetched = await props.api.result(task.task_id, isMedicalTask.value ? 'all' : undefined, current.signal)
    if (!current.signal.aborted) result.value = fetched
  } catch (error) {
    if (isAbort(error) || current.signal.aborted) return
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) { emit('unauthorized'); return }
      const action = resultConflictAction(error, task.status, refreshedOnce.value)
      if (action === 'refresh') {
        refreshedOnce.value = true
        await fetchResult()
        return
      }
      result.value = null
      failed.value = { code: error.card.code, error_id: error.card.error_id }
    } else {
      result.value = null
      failed.value = { code: 'UNKNOWN_ERROR', error_id: null }
    }
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch([() => props.open, taskKey] as const, ([open], [wasOpen]) => {
  if (!open) { controller?.abort(); return }
  if (!wasOpen) {
    dirty.value = false; stale.value = false; reviewError.value = ''
    result.value = null
    failed.value = null
    filter.value = 'all'
    activeSource.value = null
    refreshedOnce.value = false
  } else if (dirty.value && result.value) { stale.value = true; return }
  void fetchResult()
}, { immediate: true })
async function refreshDraft() {
  if (dirty.value) { try { await ElMessageBox.confirm('刷新将放弃当前未提交草稿；请先记录需要保留的修正。', '读取最新版本') } catch { return } }
  dirty.value = false; stale.value = false; reviewError.value = ''; result.value = null; await fetchResult()
}
async function saveReview(body: ReviewBody) {
  if (!props.api || !result.value || saving.value || stale.value) return
  const taskId = result.value.task_id
  saving.value = true; reviewError.value = ''; saveController = new AbortController()
  try {
    const updated = await props.api.review(taskId, body, saveController.signal)
    dirty.value = false; emit('reviewed', updated)
    const fresh = await props.api.result(taskId, updated.doc_type === 'MEDICAL_REPORT' ? 'all' : undefined, saveController.signal)
    result.value = fresh
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) { if (error.card.http_status === 401) emit('unauthorized'); if (error.card.http_status === 409) stale.value = true; reviewError.value = errorMessages[error.card.code] + (error.retryAfterSeconds === undefined ? `（错误编号 ${error.card.error_id}）` : `可在 ${error.retryAfterSeconds} 秒后重试。`) }
    else reviewError.value = '提交未确认，草稿已保留。请查任务状态，不要盲目重复提交。'
  } finally { saving.value = false }
}
async function beforeClose(done: () => void) {
  if (saving.value) return
  if (dirty.value) { try { await ElMessageBox.confirm('关闭会丢弃尚未提交的草稿，是否继续？', '未保存修正') } catch { return } }
  controller?.abort(); done()
}
onBeforeUnmount(() => { disposed = true; controller?.abort(); saveController?.abort(); exportController?.abort() })
const previewTask = computed(() => props.task && result.value ? { ...props.task, run_id: result.value.run_id, result_revision: result.value.result_revision } : props.task)
watch(() => result.value ? resultKey(result.value) : '', () => { activeSource.value = null })
watch(() => props.open, open => { if (!open) activeSource.value = null })
function locate(source: FieldSource) {
  // 户口本页级定位（整页对照，无 bbox、无红框 overlay——SourcePreview 的红框门禁不含户口本）。
  // 契约见 FRONTEND_FIELDS.md“原图定位与人工操作”：户口本仅做页级来源对照，真实样本验收仍待补充。
  if (['MEDICAL_REPORT','TABLE','GENERIC','BANK_CARD','INTERVIEW_FORM','HOUSEHOLD_REGISTER'].includes(result.value?.doc_type ?? '')) activeSource.value = sourceSelection(source)
}
// 点击抽屉版面任意空白（字段面板的间隙、说明文字、边缘等，非交互控件、非页面图片）取消定位红框；
// 定位红框会一直遮着原图，需要一个随手可及的取消方式。交互控件与图片各自的点击语义不受影响。
function onBodyClick(event: MouseEvent) {
  if (isInteractiveClickTarget(event.target)) return
  if (!activeSource.value) return
  activeSource.value = null
}
const regions = computed(() => (props.task?.pages ?? []).flatMap(page => (page.regions ?? []).map(region => ({ region_id: region.region_id, page: page.page_index }))))

// 字段/项目级"待核对/核对项"标签已按需求移除；这里是未自动接受问题文案的唯一汇总出口。
// 字段级缺失有下方编辑区的红边+（必填）兜底，不重复列；项目/清单级缺失没有其他载体，照常列出。
const blockingIssues = computed(() => {
  if (!result.value) return []
  const fieldLabels = new Set((result.value.fields ?? Object.values(result.value.basic_info ?? {})).map(field => field.label))
  return collectIssues(result.value).filter(row => !canAcceptIssue(row.issue) && !(row.issue.code === 'MISSING' && fieldLabels.has(row.scope)))
})
// scope 形如"项目：谷丙转氨酶"时直接取项目名，避免渲染出"项目：谷丙转氨酶：…"双冒号；余量附项目名便于搜索定位。
const issueLabel = (scope: string) => (scope.startsWith('项目：') ? scope.slice(3) : scope)
const noticeSegments = computed(() => blockingIssues.value.slice(0, 2).map(row => ({ text: `${issueLabel(row.scope)}：${row.issue.message.replace(/。$/, '')}`, jump: row.jump })))
const noticeTail = computed(() => {
  const restNames = [...new Set(blockingIssues.value.slice(2).map(row => issueLabel(row.scope)))]
  return restNames.length ? `；另有${restNames.slice(0, 4).join('、')}${restNames.length > 4 ? `等${restNames.length}项` : ''}` : ''
})
// 红字里的前两条问题可点击：展开并滚动到复核编辑区中对应字段/项目/清单/成员；seq 递增让重复点击同一目标也能再次触发。
const issueFocus = ref<(IssueJump & { seq: number }) | null>(null)
let issueFocusSeq = 0
function jumpToIssue(jump: IssueJump) { issueFocus.value = { ...jump, seq: ++issueFocusSeq } }

// 左右分栏宽度：可拖动的分隔条，双击复位；仅内存保存，不落任何存储。
const leftWidth = ref(40)
const dragging = ref(false)
let dragStartX = 0, dragStartPct = 0, dragContainerWidth = 0
function onSplitterDown(event: PointerEvent) {
  const splitter = event.currentTarget
  const container = splitter instanceof HTMLElement ? splitter.parentElement : null
  if (!(container instanceof HTMLElement)) return
  dragging.value = true
  dragStartX = event.clientX
  dragStartPct = leftWidth.value
  dragContainerWidth = container.getBoundingClientRect().width
  if (splitter instanceof HTMLElement) splitter.setPointerCapture(event.pointerId)
  document.body.style.userSelect = 'none'
}
function onSplitterMove(event: PointerEvent) {
  if (!dragging.value || !dragContainerWidth) return
  const deltaPercent = ((event.clientX - dragStartX) / dragContainerWidth) * 100
  leftWidth.value = Math.min(68, Math.max(24, dragStartPct + deltaPercent))
}
function onSplitterUp() {
  if (!dragging.value) return
  dragging.value = false
  document.body.style.userSelect = ''
}
function resetSplit() { leftWidth.value = 40 }

const exporting = ref(false)
let exportController: AbortController | undefined
const exportBlocked = computed(() => {
  if (!props.canWrite) return '当前只读账号无 Excel 导出权限'
  if (dirty.value || saving.value) return '有未保存的修正，请先点击「保存修正」，保存成功后才能导出'
  return result.value ? exportBlockReason([result.value]) : '请先读取已保存的结果'
})
async function runExport() {
  const task = props.task
  if (!props.api || !task || !result.value || exporting.value || !props.canWrite) return
  const block = exportBlocked.value
  if (block) { ElMessage.warning(block); return }
  const filename = spreadsheetName([result.value.doc_type])
  exportController = new AbortController()
  exporting.value = true
  try {
    const blob = await props.api.export({
      task_ids: [task.task_id], masked: false,
      versions: [{ task_id: task.task_id, run_id: result.value.run_id, result_revision: result.value.result_revision }],
    }, exportController.signal)
    if (exportController.signal.aborted) return
    downloadBlob(blob, result.value.doc_type === 'TABLE' ? blob.downloadName ?? '表格.xlsx' : filename)
    ElMessage.success('已导出 Excel 文件。')
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) { emit('unauthorized'); return }
      ElMessage.error(`${errorMessages[error.card.code]}${error.card.error_id ? `（错误编号 ${error.card.error_id}）` : ''}`)
    } else ElMessage.error(errorMessages.UNKNOWN_ERROR)
  } finally { exporting.value = false }
}
</script>

<template>
  <el-drawer data-guide-scope="task-result"
    :model-value="open"
    size="90%"
    :close-on-click-modal="true"
    destroy-on-close
    append-to-body
    :before-close="beforeClose"
    @update:model-value="value => emit('update:open', value)"
  >
    <template #header>
      <div class="drawer-head">
        <span class="drawer-title">{{ task?.file_name ?? (task ? `任务 ${task.task_id.slice(0, 8)}` : '识别结果') }}</span>
        <span class="drawer-actions">
          <OperationGuide label="本页指引" :context="detailGuideContext(result?.doc_type)" scope="task-result" :can-write="canWrite" :active="open && !!result && !loading && !saving" :reset-key="taskKey" />
          <el-tooltip
            v-if="result && task && exportBlocked"
            :content="exportBlocked"
            placement="bottom"
          >
            <span data-guide="detail-export"><el-button :icon="Download" disabled>导出 Excel</el-button></span>
          </el-tooltip>
          <!-- NEED_REVIEW 时保存修正才是主操作：导出降为 plain 次级按钮（白底蓝描边），与不可导出的灰色禁用态明确区分；导出门禁不变，仍可点。 -->
          <span v-else-if="result && task" data-guide="detail-export">
            <el-button type="primary" :plain="task.status === 'NEED_REVIEW'" :icon="Download" :loading="exporting" @click="runExport()">导出 Excel</el-button>
          </span>
        </span>
      </div>
    </template>
    <div class="drawer-body" @click="onBodyClick">
      <div v-if="loading" class="detail-loading">
        <span class="rainbow-spinner detail-spinner" aria-hidden="true"></span>
        <p class="loading-slogan">成就每一位贡献者</p>
      </div>
      <el-result v-else-if="failed" icon="warning" :title="errorMessages[failed.code]">
        <template #sub-title>
          <p v-if="failed.error_id">错误编号：{{ failed.error_id }}</p>
          <p class="drawer-hint">可以关闭后回到任务列表，稍后重试或对该任务发起重跑。</p>
        </template>
      </el-result>
      <template v-else-if="result && task">
        <el-alert v-if="stale || reviewError" type="warning" :closable="false">{{ reviewError || '任务结果或必填设置已更新，当前草稿已保留；请明确刷新后重新核对。' }}<el-button @click="refreshDraft">读取最新版本</el-button></el-alert>
        <p v-if="task.status === 'NEED_REVIEW'" class="drawer-notice" role="note">该任务包含需要人工核对的内容<span v-if="noticeSegments.length">（<template v-for="(segment, i) in noticeSegments" :key="i">{{ i ? '；' : '' }}<button v-if="segment.jump && result.doc_type !== 'TABLE'" type="button" class="issue-jump" title="定位到人工核对与修正区的对应条目" @click="segment.jump && jumpToIssue(segment.jump)">{{ segment.text }}</button><span v-else>{{ segment.text }}</span></template>{{ noticeTail }}）</span>，请结合左侧原图核对后再使用。</p>
        <el-alert v-if="task.error" type="error" :closable="false" show-icon class="drawer-alert">
          {{ errorMessages[task.error.code] }}{{ task.error.error_id ? `（错误编号 ${task.error.error_id}）` : '' }}
        </el-alert>
        <BankCardRecovery v-if="open && api && previewTask && canWrite && (needsBankCrop(result) || result.doc_type === 'TABLE')" :key="resultKey(result)" :task="previewTask" :api="api" :monitor="monitor" :disabled="dirty || saving || stale" @submitted="emit('bank-retried')" @preview="(files, tasks) => emit('preview', files, tasks)" @unauthorized="emit('unauthorized')" />
        <div class="drawer-split" :style="{ '--left-width': `${leftWidth}%` }">
          <aside class="split-left">
            <SourcePreview v-if="previewTask" :key="`${previewTask.task_id}:${previewTask.run_id}:${previewTask.result_revision}`" :task="previewTask" :api="api" :can-write="canWrite" :active="open" :ocr-enabled="!stale && !saving" :preview="preview" :source="activeSource" @clear-source="activeSource = null" @unauthorized="emit('unauthorized')" />
          </aside>
          <div class="splitter" :class="{ dragging }" role="separator" aria-orientation="vertical" title="拖动调整左右宽度，双击复位" @pointerdown="onSplitterDown" @pointermove="onSplitterMove" @pointerup="onSplitterUp" @pointercancel="onSplitterUp" @dblclick="resetSplit"></div>
          <div class="split-right">
            <TableReview v-if="result.doc_type === 'TABLE'" :key="resultKey(result)" :result="result" :can-write="canWrite && !stale" :busy="saving" @dirty="dirty=$event" @save="saveReview" @locate="locate" />
            <ResultView v-if="result.doc_type !== 'TABLE'"
              :result="result"
              :filter="filter"
              @locate="locate"
              @update:filter="value => (filter = value)"
            />
            <GenericSources v-if="result.doc_type === 'GENERIC' && result.generic" :original="result.generic" @locate="locate" />
            <ReviewEditor v-if="result.doc_type !== 'TABLE'" :key="resultKey(result)" :result="result" :profile="catalogue.find(p => p.doc_type === result!.doc_type)" :can-write="canWrite && !stale" :busy="saving" :page-count="task.actual_source_page_count ?? 0" :regions="regions" :focus="issueFocus" @dirty="dirty = $event" @save="saveReview" @locate="locate" />
          </div>
        </div>
      </template>
      <el-empty v-else description="暂无结果" />
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-body { min-height: 200px; }
/* 结果详情加载层：转圈固定在屏幕正中，覆盖整个视口，读取期间拦截误点。 */
.detail-loading {
  position: fixed; inset: 0; z-index: 10;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 24px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(2px);
  cursor: progress;
}
.detail-spinner { width: 46px; height: 46px; }
.loading-slogan {
  margin: 0;
  font-family: 'STZhongsong', 'Noto Serif SC', 'KaiTi', 'SimSun', serif;
  font-size: 22px; font-weight: 600;
  letter-spacing: 0.3em; text-indent: 0.3em;
  background: linear-gradient(90deg, #ff6b6b, #ffa94d, #ffd43b, #69db7c, #38d9a9, #4dabf7, #9775fa, #ff6b6b);
  background-size: 200% auto;
  -webkit-background-clip: text; background-clip: text; color: transparent;
  animation: slogan-shimmer 2.8s linear infinite;
}
@keyframes slogan-shimmer { to { background-position: 200% center; } }
@media (prefers-reduced-motion: reduce) { .loading-slogan { animation-duration: 6s; } }
.drawer-alert { margin-bottom: 12px; }
/* 人工核对提示：与字段下的号码校验提示（number-length-hint）同款，一句红字，不用告警大条。 */
.drawer-notice { margin: 0 0 10px; color: var(--el-color-danger); line-height: 1.5; }
/* 红字问题段可点击定位：保持红字观感，虚线下划示意可点，悬停/聚焦转为实线；不动浏览器默认聚焦轮廓。 */
.issue-jump { padding: 0; border: 0; background: none; font: inherit; color: inherit; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
.issue-jump:hover, .issue-jump:focus-visible { text-decoration-style: solid; }
.drawer-hint { color: var(--el-text-color-secondary); font-size: 12px; }
.drawer-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-right: 28px; min-width: 0; }
.drawer-title { font-size: 16px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drawer-actions { display: inline-flex; gap: 8px; flex-shrink: 0; }
.drawer-split { display: grid; grid-template-columns: minmax(280px, var(--left-width, 40%)) 6px minmax(0, 1fr); gap: 8px; align-items: start; }
.split-left { position: sticky; top: 0; max-height: calc(100vh - 120px); overflow: auto; min-width: 0; }
.splitter { position: sticky; top: 0; height: calc(100vh - 120px); cursor: col-resize; border-radius: 3px; background: transparent; transition: background 0.2s; }
.splitter:hover, .splitter.dragging { background: var(--el-color-primary-light-7); }
.split-right { min-width: 0; }
.split-right :deep(.el-descriptions td), .split-right :deep(.el-descriptions th) { overflow-wrap: anywhere; }
@media (max-width: 1280px) {
  .drawer-split { grid-template-columns: 1fr; }
  .splitter { display: none; }
  .split-left { position: static; max-height: none; }
}
</style>
