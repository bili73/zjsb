<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Crop } from '@element-plus/icons-vue'
import RegionOcrDialog from './RegionOcrDialog.vue'
import { mostVisiblePage } from '../regionOcr.ts'
import { resultKey } from '../business.ts'
import { isInteractiveClickTarget } from '../interactiveTarget.ts'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import type { FieldSource, Task } from '../business.ts'
import type { LocalPreview } from '../workbench.ts'
import { errorMessages } from '../diagnostics.ts'
const props = withDefaults(defineProps<{ task: Task; api: BusinessApi | null; preview?: LocalPreview; source: FieldSource | null; canWrite: boolean; active?: boolean; ocrEnabled?: boolean }>(), { active: true, ocrEnabled: true })
const emit = defineEmits<{ (e: 'unauthorized'): void; (e: 'clear-source'): void }>()

// 每页独立状态：懒加载（IntersectionObserver 滚动到附近才请求），点击进全屏缩放查看器。
interface PageEntry { url: string; corrected: boolean; loaded: boolean; status: 'idle' | 'loading' | 'done' | 'error' }
const maxPage = computed(() => Math.max(1, props.task.actual_source_page_count ?? props.task.page_count))
const entries = reactive<PageEntry[]>(Array.from({ length: maxPage.value }, () => ({ url: '', corrected: false, loaded: false, status: 'idle' })))
const failure = ref('')
const jumpPage = ref(1)
const loading = ref(false)
const controllers = new Map<number, AbortController>()
interface PageLoad { page: number; epoch: number; priority: number; promise: Promise<void>; resolve: () => void }
const pageLoads = new Map<number, PageLoad>()
const pendingPages = new Map<number, PageLoad>()
let requestEpoch = 0, requestPriority = 0, disposed = false
const maxRequests = 2
const pageEls = new Map<number, HTMLElement>()
const visiblePages = new Set<number>()
const previewEl = ref<HTMLElement>()
const pageListEl = ref<HTMLElement>()
const pageToolsEl = ref<HTMLElement>()
const ocrOpen = ref(false), ocrPage = ref(1), ocrCinema = ref(false)
const originalUrl = ref(''), originalLoading = ref(false), localOpen = ref(false)
let originalController: AbortController | undefined
let observer: IntersectionObserver | undefined
let layoutObserver: ResizeObserver | undefined
let previewViewport: HTMLElement | null = null
let selection = 0
let navigating = false
let alignmentFrame = 0
const browsingEvents = ['wheel', 'touchstart', 'pointerdown', 'keydown'] as const

function cancelNavigation() {
  selection++
  navigating = false
  if (alignmentFrame) cancelAnimationFrame(alignmentFrame)
  alignmentFrame = 0
}

function alignSource() {
  if (!navigating || alignmentFrame) return
  const current = selection
  alignmentFrame = requestAnimationFrame(() => {
    alignmentFrame = 0
    if (!navigating || current !== selection || !props.source) return
    const page = Math.min(Math.max(1, props.source.page ?? 1), maxPage.value)
    const entry = entries[page - 1]
    if (!entry || entry.status === 'loading' || (entry.url && !entry.loaded)) return
    const pageEl = pageEls.get(page)
    const target = pageEl?.querySelector('.bbox-overlay') ?? pageEl
    // Retarget smoothly when lazy pages change the destination during movement.
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function setPageRef(el: unknown, page: number) {
  if (el instanceof HTMLElement) {
    pageEls.set(page, el)
    observer?.observe(el)
  } else pageEls.delete(page)
}

function clearPage(page: number) {
  const entry = entries[page - 1]
  if (entry?.url) URL.revokeObjectURL(entry.url)
  if (entry) { entry.url = ''; entry.corrected = false; entry.loaded = false; entry.status = 'idle' }
}

function resetAll() {
  requestEpoch++
  closeOriginal()
  localOpen.value = false
  for (const job of pageLoads.values()) job.resolve()
  pageLoads.clear()
  pendingPages.clear()
  for (const controller of controllers.values()) controller.abort()
  controllers.clear()
  for (let page = 1; page <= entries.length; page++) clearPage(page)
}

function loadPage(page: number, priority = false): Promise<void> {
  if (disposed || !props.active) return Promise.resolve()
  if (!props.api || !props.canWrite) { failure.value = props.canWrite ? '预览组件未就绪。' : '当前只读账号无原图预览权限。'; return Promise.resolve() }
  const entry = entries[page - 1]
  if (!entry || entry.url) return Promise.resolve()
  const existing = pageLoads.get(page)
  if (existing) { if (priority) existing.priority = ++requestPriority; return existing.promise }
  if (entry.status === 'error' && !priority) return Promise.resolve()
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  const job = { page, epoch: requestEpoch, priority: priority ? ++requestPriority : 0, promise, resolve }
  pageLoads.set(page, job)
  pendingPages.set(page, job)
  entry.status = 'loading'
  failure.value = ''
  drainPages()
  return promise
}

function drainPages() {
  if (disposed || !props.active || !props.api || !props.canWrite) return
  while (controllers.size < maxRequests && pendingPages.size) {
    const [page, job] = [...pendingPages].sort((a, b) => b[1].priority - a[1].priority)[0]!
    pendingPages.delete(page)
    void readPage(job)
  }
}

async function readPage(job: PageLoad) {
  const { page, epoch } = job
  const entry = entries[page - 1]!
  const current = new AbortController()
  controllers.set(page, current)
  try {
    const response = await props.api!.preview(props.task, page, current.signal, undefined, 'display')
    if (current.signal.aborted || epoch !== requestEpoch || disposed) return
    entry.url = URL.createObjectURL(response.blob)
    entry.corrected = response.corrected
    entry.status = 'done'
  } catch (error) {
    if (isAbort(error) || current.signal.aborted || epoch !== requestEpoch || disposed) return
    entry.status = 'error'
    if (error instanceof ApiFailure) { failure.value = errorMessages[error.card.code]; if (error.card.http_status === 401) emit('unauthorized') }
  } finally {
    if (controllers.get(page) === current) controllers.delete(page)
    if (pageLoads.get(page) === job) pageLoads.delete(page)
    job.resolve()
    drainPages()
  }
}

function onIntersect(records: IntersectionObserverEntry[]) {
  for (const record of records) {
    const page = Number((record.target as HTMLElement).dataset.page)
    if (!page) continue
    if (record.isIntersecting) { visiblePages.add(page); void loadPage(page) } else {
      visiblePages.delete(page)
      dropPendingPage(page)
    }
  }
}

function dropPendingPage(page: number) {
  const job = pendingPages.get(page)
  if (job && !job.priority) { pendingPages.delete(page); pageLoads.delete(page); clearPage(page); job.resolve() }
}

function scrollViewportFor(element: HTMLElement | null): HTMLElement | null {
  for (let current = element; current; current = current.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(current).overflowY)
        && current.clientHeight > 0 && current.scrollHeight > current.clientHeight) return current
  }
  return null
}

function bindViewport() {
  const next = scrollViewportFor(previewEl.value?.parentElement ?? null)
  if (next === previewViewport && observer) return
  for (const event of browsingEvents) previewViewport?.removeEventListener(event, cancelNavigation)
  observer?.disconnect()
  visiblePages.clear()
  for (const page of pendingPages.keys()) dropPendingPage(page)
  previewViewport = next
  observer = new IntersectionObserver(onIntersect, { root: previewViewport, rootMargin: '75% 0px' })
  for (const el of pageEls.values()) observer.observe(el)
  for (const event of browsingEvents) previewViewport?.addEventListener(event, cancelNavigation, { passive: true })
}

function goTo(page: number) {
  cancelNavigation()
  const target = Math.min(Math.max(1, Math.floor(page || 1)), maxPage.value)
  jumpPage.value = target
  pageEls.get(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  void loadPage(target, true)
}

function reloadAll() {
  cancelNavigation()
  resetAll()
  for (const page of visiblePages) void loadPage(page)
}

function openOcr() {
  if (!props.api || !props.canWrite || !props.active || !props.ocrEnabled) return
  cancelNavigation()
  const viewport = previewViewport?.getBoundingClientRect()
  const top = Math.max(0, viewport?.top ?? 0, pageToolsEl.value?.getBoundingClientRect().bottom ?? 0)
  const bottom = Math.min(window.innerHeight, viewport?.bottom ?? window.innerHeight)
  const pages = [...pageEls].map(([page, el]) => { const rect = el.getBoundingClientRect(); return { page, top: rect.top, bottom: rect.bottom } })
  ocrPage.value = mostVisiblePage(pages, top, bottom, jumpPage.value)
  ocrCinema.value = false
  ocrOpen.value = true
}
// 入口提示随可用性变化：不可用时说明原因，而不是让按钮沉默失效。
const ocrTip = computed(() => props.ocrEnabled
  ? '在原图上拖动框选任意文字区域，立即识别、可复制粘贴，适合补录遗漏或识别不准的字段'
  : '当前材料暂无服务端校正页，暂不支持框选识别')

function openOcrAt(page: number) {
  if (!props.api || !props.canWrite || !props.active || !props.ocrEnabled) return
  cancelNavigation()
  ocrPage.value = page
  // 点击页面图 = 沿用“查看原图”的全屏大图观感，在其中做二次识别。
  ocrCinema.value = true
  ocrOpen.value = true
}
function closeOriginal() {
  originalController?.abort()
  originalController = undefined
  originalLoading.value = false
  if (originalUrl.value) URL.revokeObjectURL(originalUrl.value)
  originalUrl.value = ''
}
async function openOriginal(page: number) {
  if (!props.api || !props.canWrite || !props.active || disposed) return
  cancelNavigation()
  closeOriginal()
  const current = new AbortController(), epoch = requestEpoch
  originalController = current
  originalLoading.value = true
  failure.value = ''
  try {
    const response = await props.api.preview(props.task, page, current.signal, undefined, 'original')
    if (current.signal.aborted || epoch !== requestEpoch || disposed) return
    originalUrl.value = URL.createObjectURL(response.blob)
  } catch (error) {
    if (isAbort(error) || current.signal.aborted || epoch !== requestEpoch || disposed) return
    if (error instanceof ApiFailure) { failure.value = errorMessages[error.card.code]; if (error.card.http_status === 401) emit('unauthorized') }
  } finally {
    if (originalController === current) { originalController = undefined; originalLoading.value = false }
  }
}
function onLocalToggle(event: Event) {
  localOpen.value = props.active && (event.currentTarget as HTMLDetailsElement).open
}
// 点击页面图：支持框选识别的材料直接进入原图识别对话框；否则保留原全屏缩放查看器。
function onPageClick(page: number) {
  if (props.ocrEnabled) openOcrAt(page)
  else void openOriginal(page)
}
// 定位红框会一直遮着校正页；点击版面空白处（非图片、非交互控件）取消定位，图片和按钮各有自己的语义不动。
function onSectionClick(event: MouseEvent) {
  if (isInteractiveClickTarget(event.target)) return
  if (!props.source) return
  emit('clear-source')
}
watch([() => props.active, () => props.api, () => props.canWrite, () => props.ocrEnabled, () => resultKey(props.task)], () => { ocrOpen.value = false; closeOriginal() }, { flush: 'sync' })

function overlayFor(page: number) {
  if (!['MEDICAL_REPORT','TABLE','GENERIC','BANK_CARD','INTERVIEW_FORM'].includes(props.task.doc_type ?? '') || !entries[page - 1]?.corrected || !entries[page - 1]?.loaded || !props.source?.bbox || props.source.page !== page) return null
  const [x1, y1, x2, y2] = props.source.bbox
  return { left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }
}

watch(() => props.source, source => {
  cancelNavigation()
  if (!source) return
  navigating = true
  const page = Math.min(Math.max(1, source.page ?? 1), maxPage.value)
  jumpPage.value = page
  void loadPage(page, true)
  alignSource()
}, { flush: 'post', immediate: true })
watch(() => entries.map(entry => [entry.status, entry.loaded]), alignSource, { flush: 'post' })
watch([() => props.active, () => props.api, () => props.canWrite, () => resultKey(props.task)], () => {
  cancelNavigation()
  resetAll()
  failure.value = ''
  if (props.source) {
    navigating = true
    jumpPage.value = Math.min(Math.max(1, props.source.page ?? 1), maxPage.value)
    void loadPage(jumpPage.value, true)
  }
  else void loadPage(1)
  for (const page of visiblePages) void loadPage(page)
})
onMounted(() => {
  layoutObserver = new ResizeObserver(() => { bindViewport(); alignSource() })
  if (pageListEl.value) layoutObserver.observe(pageListEl.value)
  if (previewEl.value) layoutObserver.observe(previewEl.value)
  bindViewport()
})
onBeforeUnmount(() => {
  disposed = true
  cancelNavigation()
  layoutObserver?.disconnect()
  for (const event of browsingEvents) previewViewport?.removeEventListener(event, cancelNavigation)
  observer?.disconnect()
  resetAll()
})
void (async () => {
  loading.value = true
  await loadPage(1)
  loading.value = false
})()
</script>
<template>
  <section ref="previewEl" v-loading="loading" class="source-preview" @click="onSectionClick">
    <h3>原件对照 · 服务端校正页</h3>
    <div ref="pageToolsEl" class="page-tools">
      <span>共 {{ maxPage }} 页 · {{ ocrEnabled ? '点击页面框选识别' : '点击页面放大查看' }}</span>
      <el-input-number v-model="jumpPage" :min="1" :max="maxPage" :precision="0" size="small" controls-position="right" />
      <el-button size="small" @click="goTo(jumpPage)">跳页</el-button>
      <span class="tools-spacer" />
      <el-button size="small" :disabled="!canWrite" @click="reloadAll()">重新读取</el-button>
      <el-tooltip :content="ocrTip" placement="left" effect="dark">
        <span class="ocr-entry" data-guide="source-tools"><el-button size="small" type="primary" :icon="Crop" :disabled="!api || !canWrite || !active || !ocrEnabled" @click="openOcr">框选识别文字</el-button></span>
      </el-tooltip>
    </div>
    <el-alert v-if="failure" type="warning" :closable="false">{{ failure }}</el-alert>
    <div v-if="originalLoading" role="status">正在读取清晰原图… <el-button link @click="closeOriginal">取消</el-button></div>
    <ol ref="pageListEl" class="page-list">
      <li v-for="n in maxPage" :key="n" :ref="el => setPageRef(el, n)" :data-page="n" class="page-item">
        <span class="page-no">第 {{ n }} 页</span>
        <div v-if="entries[n - 1]?.status === 'error'" class="page-error">该页读取失败。<el-button link type="primary" @click="loadPage(n, true)">重试</el-button></div>
        <el-skeleton v-else-if="entries[n - 1]?.status === 'loading'" animated class="page-skeleton" />
        <figure v-if="entries[n - 1]?.url" class="img-wrap" :title="ocrEnabled ? '点击查看原图并框选识别' : '点击查看清晰原图'" @click="onPageClick(n)">
          <el-image :src="entries[n - 1]!.url" fit="scale-down" decoding="async" class="page-image" :alt="`材料校正页 ${n}`" @load="entries[n - 1]!.loaded = true" />
          <span v-if="overlayFor(n)" class="bbox-overlay" :style="overlayFor(n)!" />
        </figure>
        <div v-else-if="entries[n - 1]?.status !== 'error' && entries[n - 1]?.status !== 'loading'" class="page-holder">滚动到此处时加载本页</div>
      </li>
    </ol>
    <el-image-viewer v-if="originalUrl" :url-list="[originalUrl]" teleported hide-on-click-modal @close="closeOriginal" />
    <details v-if="preview" :open="localOpen" class="local-preview" @toggle="onLocalToggle">
      <summary>本地上传材料（会话内，未经校正，不叠加来源框）</summary>
      <template v-if="localOpen">
        <iframe v-if="preview.kind === 'pdf'" class="pdf-frame" :src="`${preview.url}#page=${jumpPage}`" title="本地原件" />
        <el-image v-else-if="preview.kind === 'image'" :src="preview.url" :preview-src-list="[preview.url]" preview-teleported hide-on-click-modal fit="scale-down" class="local-image" alt="本地上传材料" />
        <el-alert v-else type="info" :closable="false">本浏览器可能无法直接渲染 HEIC，请在全屏查看器中确认或换用图像格式。</el-alert>
      </template>
    </details>
    <RegionOcrDialog :open="ocrOpen && active && ocrEnabled" :cinema="ocrCinema" :api="api" :task="task" :initial-page="ocrPage" :can-write="canWrite" @cancel="ocrOpen = false" @unauthorized="emit('unauthorized')" />
  </section>
</template>
<style scoped>
.page-tools { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 12px 0; padding: 8px 0; position: sticky; top: 0; z-index: 2; background: var(--el-bg-color); }
.ocr-entry { display: inline-flex; }
.tools-spacer { flex: 1; }
.page-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 16px; }
/* 滚动性能：占位与图片容器统一按 A4 比例预留高度，图片加载完成不再把下方内容顶下去（layout shift）；
   content-visibility 让视口外的页完全跳过排版和绘制，长报告滚动更轻。 */
.page-item { scroll-margin-top: 8px; content-visibility: auto; contain-intrinsic-size: auto 820px; }
.page-no { display: block; font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.page-image { width: 100%; height: 100%; display: block; }
.img-wrap { position: relative; display: block; width: 100%; margin: 0; aspect-ratio: 210 / 297; cursor: zoom-in; }
.page-holder { border: 1px dashed var(--el-border-color); border-radius: 6px; min-height: 160px; aspect-ratio: 210 / 297; display: flex; align-items: center; justify-content: center; font-size: 12px; color: var(--el-text-color-secondary); }
.page-skeleton { min-height: 160px; aspect-ratio: 210 / 297; }
.page-error { font-size: 13px; color: var(--el-color-danger); }
.bbox-overlay { position: absolute; border: 2px solid var(--el-color-danger); background: rgba(255, 93, 93, 0.14); pointer-events: none; border-radius: 2px; }
.local-preview { margin-top: 16px; }
.local-image { width: 100%; display: block; }
</style>
