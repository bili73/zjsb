<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import type { InputInstance } from 'element-plus'
import { resultKey } from '../business.ts'
import type { Task } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import { dateCopySuggestions, pointInImage, regionBox } from '../regionOcr.ts'
import type { RegionBox } from '../regionOcr.ts'

const props = withDefaults(defineProps<{ open: boolean; api: BusinessApi | null; task: Task | null; initialPage: number; canWrite: boolean; cinema?: boolean }>(), { cinema: false })
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'unauthorized'): void }>()
const page = ref(1), url = ref(''), image = ref<HTMLImageElement>(), ready = ref(false), loading = ref(false), recognizing = ref(false)
const scale = ref(1), baseWidth = ref(0), holder = ref<HTMLElement>(), stage = ref<HTMLElement>()
const stageMargin = ref({ x: 0, y: 0 })
const bbox = ref<RegionBox | null>(null), text = ref(''), confidence = ref<number | null>(null), error = ref('')
const copying = ref(false), copyDone = ref<string | null>(null), textInput = ref<InputInstance>()
const dateSuggestions = computed(() => dateCopySuggestions(text.value))
const dateInputs = new Map<string, HTMLInputElement>()
const panel = ref<HTMLElement>(), panelPos = ref<{ left: number; top: number } | null>(null), anchorTick = ref(0)
let start: { x: number; y: number } | null = null
let dragOffset: { x: number; y: number } | null = null
let generation = 0, disposed = false
let pageController: AbortController | undefined, ocrController: AbortController | undefined
const maxPage = computed(() => Math.max(1, props.task?.actual_source_page_count ?? props.task?.page_count ?? 1))
const context = computed(() => props.task ? resultKey(props.task) : '')
const boxStyle = computed(() => bbox.value ? { left: `${bbox.value[0] * 100}%`, top: `${bbox.value[1] * 100}%`,
  width: `${(bbox.value[2] - bbox.value[0]) * 100}%`, height: `${(bbox.value[3] - bbox.value[1]) * 100}%` } : {})
// 识别按钮跟随选区，但始终收在可视区内：默认贴选区下方偏右；贴近可视区底部时翻到选区上方，
// 右侧放不下时收到选区左缘——选区拖到任何位置按钮都可见可点（坐标随滚动/缩放经 anchorTick 刷新）。
const chipStyle = computed(() => {
  if (!bbox.value || !image.value || !holder.value || typeof window === 'undefined') return {}
  void anchorTick.value
  const [x1, y1, x2, y2] = bbox.value
  const imgRect = image.value.getBoundingClientRect()
  const holderRect = holder.value.getBoundingClientRect()
  const stageRect = stage.value?.getBoundingClientRect() ?? imgRect
  const CHIP_W = 124, CHIP_H = 40, GAP = 8
  const selLeft = imgRect.left + x1 * imgRect.width, selRight = imgRect.left + x2 * imgRect.width
  const selTop = imgRect.top + y1 * imgRect.height, selBottom = imgRect.top + y2 * imgRect.height
  let top = selBottom + GAP
  if (top + CHIP_H > holderRect.bottom - GAP) top = selTop - GAP - CHIP_H
  top = Math.min(Math.max(top, holderRect.top + GAP), holderRect.bottom - GAP - CHIP_H)
  let left = selRight + GAP
  if (left + CHIP_W > holderRect.right - GAP) left = selRight - CHIP_W
  left = Math.min(Math.max(left, holderRect.left + GAP), holderRect.right - GAP - CHIP_W)
  return { top: `${Math.round(top - stageRect.top)}px`, left: `${Math.round(left - stageRect.left)}px` }
})
// 结果卡片宽度随文字自适应：按最长行的字数估算，再收在视口内（250–560px）。
const popoverWidth = computed(() => {
  const lines = text.value.split('\n')
  const longest = Math.max(10, ...lines.map(line => line.length))
  return Math.round(Math.min(560, Math.max(250, longest * 14.5 + 56)))
})
// 悬浮结果窗：贴选区智能落位（右侧→左侧→覆盖选区较大空侧），不参与图片排版、永不挤成细条；按住头部可拖动。
const panelStyle = computed(() => {
  const vw = typeof window === 'undefined' ? 960 : window.innerWidth
  const vh = typeof window === 'undefined' ? 720 : window.innerHeight
  const width = Math.min(popoverWidth.value, vw - 24)
  const style: Record<string, string> = { width: `${width}px` }
  const pos = panelPos.value
  if (pos) {
    style.left = `${Math.round(pos.left)}px`; style.top = `${Math.round(pos.top)}px`
    style.maxHeight = `${Math.max(80, vh - pos.top - 12)}px`
    return style
  }
  if (!bbox.value || !image.value || typeof window === 'undefined') return style
  void anchorTick.value
  const rect = image.value.getBoundingClientRect()
  const [x1, y1, x2] = bbox.value
  const selLeft = rect.left + x1 * rect.width, selRight = rect.left + x2 * rect.width, selTop = rect.top + y1 * rect.height
  const rightGap = vw - selRight - 12, leftGap = selLeft - 12
  const left = rightGap >= width ? selRight + 12 : leftGap >= width ? selLeft - 12 - width : rightGap >= leftGap ? vw - width - 12 : 12
  style.left = `${Math.round(Math.min(Math.max(12, left), Math.max(12, vw - width - 12)))}px`
  const top = Math.round(Math.min(Math.max(12, selTop - 6), Math.max(12, vh - (dateSuggestions.value.length ? 480 : 320))))
  style.top = `${top}px`
  style.maxHeight = `${Math.max(80, vh - top - 12)}px`
  return style
})
function panelDragStart(event: PointerEvent) {
  const el = panel.value
  if (!el || event.button !== 0) return
  const rect = el.getBoundingClientRect()
  dragOffset = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  panelPos.value = { left: rect.left, top: rect.top }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function panelDragMove(event: PointerEvent) {
  if (!dragOffset || !panel.value) return
  const rect = panel.value.getBoundingClientRect()
  panelPos.value = {
    left: Math.min(Math.max(8, event.clientX - dragOffset.x), Math.max(8, window.innerWidth - rect.width - 8)),
    top: Math.min(Math.max(8, event.clientY - dragOffset.y), Math.max(8, window.innerHeight - rect.height - 8)),
  }
}
function panelDragEnd() { dragOffset = null }
// 滚轮缩放：1×–4×；1× 完整呈现整图（无滚动条），放大后容器内滚动查看细节。
function onWheel(event: WheelEvent) {
  if (!ready.value || loading.value || copying.value) return
  event.preventDefault()
  const next = scale.value * (event.deltaY < 0 ? 1.2 : 1 / 1.2)
  const rounded = Math.round(Math.min(4, Math.max(1, next)) * 100) / 100
  if (rounded === scale.value) return
  // 以鼠标指向的图片点为锚放大：该点在缩放前后都停在指针下。容器内的正向偏移用外边距表达，
  // 需要卷动的部分用 scrollLeft/Top 表达（到边时由浏览器钳制，与看图软件行为一致）。
  const img = image.value, box = holder.value
  const prevRect = img?.getBoundingClientRect(), holderRect = box?.getBoundingClientRect()
  const ratio = img && img.naturalWidth ? img.naturalHeight / img.naturalWidth : 0
  const px = event.clientX, py = event.clientY
  scale.value = rounded
  void nextTick(() => {
    syncAnchor()
    if (!box || !prevRect || !holderRect || !ratio) return
    const nx = Math.min(1, Math.max(0, (px - prevRect.left) / prevRect.width))
    const ny = Math.min(1, Math.max(0, (py - prevRect.top) / prevRect.height))
    const newW = Math.round(baseWidth.value * rounded), newH = newW * ratio
    const holderW = box.clientWidth, holderH = box.clientHeight
    const desiredX = px - holderRect.left - nx * newW
    const desiredY = py - holderRect.top - ny * newH
    if (newW <= holderW && newH <= holderH) {
      stageMargin.value = {
        x: Math.max(0, Math.round((holderW - newW) / 2)),
        y: props.cinema ? Math.max(0, Math.round((holderH - newH) / 2)) : 0,
      }
      box.scrollLeft = 0
      box.scrollTop = 0
    } else {
      stageMargin.value = { x: Math.max(0, Math.round(desiredX)), y: Math.max(0, Math.round(desiredY)) }
      void nextTick(() => {
        box.scrollLeft = Math.max(0, -desiredX)
        box.scrollTop = Math.max(0, -desiredY)
      })
    }
  })
}
const zoomLabel = computed(() => scale.value.toFixed(2).replace(/\.?0+$/, ''))
// 显式设定布局宽度：display:table 下 img 的 max-width 百分比会循环解析，不能用 CSS 适配。
const imageStyle = computed(() => baseWidth.value > 0 ? { width: `${Math.round(baseWidth.value * scale.value)}px` } : {})
// 适配宽度：影院模式（点击查看原图）整页包含适配——报告类长图也刚好铺满屏幕并居中，细节靠滚轮放大；
// 常规对话框沿用原规则：整图适配，长图整图缩得过小时按宽度铺开、纵向滚动。
function measureFit() {
  const img = image.value, box = holder.value
  if (!img?.naturalWidth || !box?.clientWidth) return
  const nw = img.naturalWidth, nh = img.naturalHeight
  const hw = box.clientWidth, hh = box.clientHeight || hw
  const whole = Math.min(hw / nw, hh / nh, 1)
  baseWidth.value = Math.max(1, Math.round(props.cinema || nw * whole >= hw * 0.45 ? nw * whole : Math.min(hw, nw)))
  const displayH = baseWidth.value * (nh / nw)
  stageMargin.value = {
    x: Math.max(0, Math.round((hw - baseWidth.value) / 2)),
    y: props.cinema ? Math.max(0, Math.round((hh - displayH) / 2)) : 0,
  }
}
function onImageLoad() { ready.value = true; measureFit() }
// 悬浮窗锚点跟手：容器滚动、窗口缩放、页面滚动都会改变选区的视口位置。
function syncAnchor() { anchorTick.value++ }
function onViewportChange() { measureFit(); syncAnchor() }
function invalidate() {
  generation++; pageController?.abort(); ocrController?.abort()
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''; ready.value = false; loading.value = false; recognizing.value = false; copying.value = false; copyDone.value = null
  dateInputs.clear()
  scale.value = 1; baseWidth.value = 0; stageMargin.value = { x: 0, y: 0 }; panelPos.value = null; dragOffset = null
  bbox.value = null; start = null; text.value = ''; confidence.value = null; error.value = ''
}
async function loadPage() {
  invalidate()
  if (!props.open || !props.api || !props.task || !props.canWrite || disposed) return
  const current = generation, client = props.api, task = { ...props.task }, selectedPage = page.value
  const controller = new AbortController(); pageController = controller; loading.value = true
  try {
    const result = await client.preview(task, selectedPage, controller.signal)
    if (current !== generation || controller.signal.aborted || props.api !== client || disposed) return
    if (!result.corrected) throw new Error('UNCORRECTED_PREVIEW')
    url.value = URL.createObjectURL(result.blob)
  } catch (failure) {
    if (current !== generation || controller.signal.aborted || disposed || isAbort(failure)) return
    if (failure instanceof ApiFailure && failure.card.http_status === 401) emit('unauthorized')
    error.value = failure instanceof ApiFailure ? errorMessages[failure.card.code] : '无法读取校正原图，请关闭后重试或手工填写。'
  } finally { if (current === generation) loading.value = false }
}
watch(page, () => { void loadPage() }, { flush: 'sync' })
watch([() => props.open, () => props.api, context, () => props.initialPage, () => props.canWrite], () => {
  const initial = props.open ? Math.min(maxPage.value, Math.max(1, Math.floor(props.initialPage || 1))) : 1
  if (page.value !== initial) page.value = initial
  else void loadPage()
}, { immediate: true, flush: 'sync' })
onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('resize', onViewportChange)
  document.addEventListener('scroll', syncAnchor, true)
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', onViewportChange)
    document.removeEventListener('scroll', syncAnchor, true)
  }
  disposed = true; invalidate()
})
function down(event: PointerEvent) {
  if (!ready.value || recognizing.value || copying.value || !image.value?.naturalWidth) return
  start = pointInImage(event.clientX, event.clientY, image.value.getBoundingClientRect())
  bbox.value = null; text.value = ''; confidence.value = null; error.value = ''; copyDone.value = null; panelPos.value = null
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (!start || !image.value) return
  bbox.value = regionBox(start, pointInImage(event.clientX, event.clientY, image.value.getBoundingClientRect()))
}
function up(event: PointerEvent) { move(event); start = null }
function dismissResult() { text.value = ''; confidence.value = null; copyDone.value = null; panelPos.value = null }
async function recognize() {
  if (!props.open || !props.canWrite || !props.api || !props.task || !bbox.value || !ready.value || recognizing.value || copying.value) return
  const selected = [...bbox.value] as RegionBox, img = image.value
  if (!img || (selected[2] - selected[0]) * img.naturalWidth < 8 || (selected[3] - selected[1]) * img.naturalHeight < 8 ||
    (selected[2] - selected[0]) * (selected[3] - selected[1]) * img.naturalWidth * img.naturalHeight > 2_000_000) {
    error.value = '请框选文字值，选区边长至少8像素、面积不超过200万像素。'; return
  }
  const current = generation, client = props.api, task = { ...props.task }
  const controller = new AbortController(); ocrController = controller
  recognizing.value = true; text.value = ''; confidence.value = null; error.value = ''; copyDone.value = null; panelPos.value = null
  try {
    const result = await client.ocrRegion(task, null, page.value, selected, controller.signal)
    if (current !== generation || controller.signal.aborted || props.api !== client || disposed || !props.open || !props.canWrite) return
    text.value = result.text; confidence.value = result.confidence
    await nextTick()
    if (current === generation && !disposed && props.open) { textInput.value?.focus(); textInput.value?.select() }
  } catch (failure) {
    if (current !== generation || controller.signal.aborted || disposed || isAbort(failure)) return
    if (failure instanceof ApiFailure && failure.card.http_status === 401) emit('unauthorized')
    error.value = failure instanceof ApiFailure ? errorMessages[failure.card.code] : errorMessages.REGION_OCR_UNAVAILABLE
  } finally { if (current === generation) recognizing.value = false }
}
async function copyResult(value = text.value, input: { focus(): void; select(): void } | undefined = textInput.value) {
  if (!props.open || !props.canWrite || disposed || recognizing.value || copying.value || !value.trim()) return
  const current = generation
  copying.value = true; copyDone.value = null; error.value = ''
  try {
    if (!navigator.clipboard?.writeText) throw new Error('CLIPBOARD_UNAVAILABLE')
    await navigator.clipboard.writeText(value)
    if (current === generation && !disposed && props.open && props.canWrite) copyDone.value = value
  } catch {
    if (current !== generation || disposed || !props.open || !props.canWrite) return
    error.value = '自动复制未成功，请选中文字，使用 Ctrl+C（Mac 为 ⌘C）复制。'
    copying.value = false
    await nextTick()
    if (current === generation && !disposed && props.open) { input?.focus(); input?.select() }
  } finally { if (current === generation) copying.value = false }
}
</script>

<template>
  <el-dialog :model-value="open" title="框选识别 · 提取原件文字" :width="cinema ? '100%' : 'min(1120px, 96vw)'" :fullscreen="cinema" :show-close="!cinema" top="3vh" append-to-body :modal-class="cinema ? 'region-cinema-mask' : ''" :close-on-click-modal="false" @close="emit('cancel')">
    <p v-if="!cinema">拖动框选需要的文字（可多行），点击选区旁的「识别选区」；识别结果以悬浮卡片显示（可拖动、不遮挡选区），核对修改后复制粘贴，粘贴后仍需保存修正。</p>
    <div class="region-tools" :class="{ 'region-cinema-bar': cinema }">
      <span>第 {{ page }} / {{ maxPage }} 页</span>
      <el-input-number v-model="page" :min="1" :max="maxPage" :precision="0" size="small" :disabled="recognizing || copying" aria-label="选择原件页码" />
      <el-button :disabled="recognizing || copying || loading" @click="loadPage">重新读取原图</el-button>
      <span v-if="scale > 1" class="zoom-hint">已放大 ×{{ zoomLabel }}<el-button link size="small" :disabled="recognizing || copying" @click="scale = 1">复位</el-button></span>
      <span class="zoom-hint">{{ cinema ? '拖动框选文字 · 滚轮缩放 · ESC 退出' : '滚轮缩放图片' }}</span>
    </div>
    <div v-loading="loading" ref="holder" class="region-stage-holder" :class="{ 'is-cinema': cinema }" @wheel.prevent="onWheel" @scroll="syncAnchor">
      <div v-if="url" ref="stage" class="region-stage" :style="{ marginLeft: `${stageMargin.x}px`, marginTop: `${stageMargin.y}px` }" @pointerdown.prevent="down" @pointermove.prevent="move" @pointerup.prevent="up" @pointercancel="start = null">
        <img ref="image" :src="url" :style="imageStyle" :alt="`第${page}页，拖动框选文字`" draggable="false" @load="onImageLoad" @error="ready = false; error = '原图加载失败，请重新读取。'" />
        <span v-if="bbox" class="region-selection" :style="boxStyle" />
        <span v-if="bbox" class="region-chip" :style="chipStyle" @pointerdown.stop @click.stop>
          <el-button type="primary" :icon="Search" :loading="recognizing" :disabled="copying" class="recognize-chip" @click="recognize">识别选区</el-button>
        </span>
      </div>
    </div>
    <button v-if="cinema" type="button" class="region-cinema-close" aria-label="退出查看（Esc）" @click="emit('cancel')">×</button>
    <el-alert v-if="error" type="warning" :closable="false" class="region-error" :class="{ 'is-cinema': cinema }">{{ error }}</el-alert>
    <Teleport to="body">
      <div v-if="open && confidence !== null" ref="panel" class="region-panel" :style="panelStyle" role="dialog" aria-label="选区识别结果">
        <div class="region-panel-head" @pointerdown.prevent="panelDragStart" @pointermove="panelDragMove" @pointerup="panelDragEnd" @pointercancel="panelDragEnd">
          <strong>识别结果</strong>
          <el-tag size="small" :type="confidence < 0.8 ? 'warning' : 'success'" effect="light">置信度 {{ Math.round(confidence * 100) }}%{{ confidence < 0.8 ? ' · 较低' : '' }}</el-tag>
          <button type="button" class="region-panel-close" aria-label="收起识别结果" @pointerdown.stop @click="dismissResult">×</button>
        </div>
        <el-input ref="textInput" v-model="text" type="textarea" :autosize="{ minRows: 2, maxRows: 10 }" maxlength="4096" :disabled="copying" aria-label="选区识别文字，可修改或复制" />
        <div class="region-panel-foot">
          <span class="region-panel-note">请对照原图核对；此分数不改变原字段置信度。</span>
          <el-button size="small" :type="copyDone === text ? 'success' : 'primary'" :loading="copying" :disabled="!text.trim()" @click="copyResult()">{{ copyDone === text ? '已复制' : '复制文字' }}</el-button>
        </div>
        <div v-if="dateSuggestions.length" class="date-suggestions" aria-label="日期复制建议">
          <strong>日期复制建议</strong>
          <p class="region-panel-note">只转换格式，不补日期；请核对原图后复制。</p>
          <div v-for="suggestion in dateSuggestions" :key="suggestion.value" class="date-suggestion">
            <span class="date-suggestion-source">{{ suggestion.raw }}</span>
            <div class="date-suggestion-actions">
              <input :ref="element => { if (element) dateInputs.set(suggestion.value, element as HTMLInputElement); else dateInputs.delete(suggestion.value) }"
                :value="suggestion.value" :aria-label="`日期建议 ${suggestion.value}`" readonly />
              <el-button size="small" :type="copyDone === suggestion.value ? 'success' : 'primary'" :disabled="copying" @click="copyResult(suggestion.value, dateInputs.get(suggestion.value))">{{ copyDone === suggestion.value ? '已复制' : '复制日期' }}</el-button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
    <template #footer><el-button v-if="!cinema" @click="emit('cancel')">关闭</el-button></template>
  </el-dialog>
</template>

<style scoped>
.region-tools { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 12px; }
.zoom-hint { font-size: 12px; color: var(--el-text-color-secondary); display: inline-flex; align-items: center; gap: 4px; }
/* 高度固定：整图适配依赖稳定的容器尺寸；1× 无滚动条，放大后出现滚动条。 */
.region-stage-holder { height: min(58vh, max(220px, calc(94dvh - 410px))); overflow: auto; }
.region-stage { position: relative; display: table; touch-action: none; user-select: none; cursor: crosshair; }
.region-stage img { display: block; pointer-events: none; }
/* 选区框：红色描边，便于在整页原图上快速定位。 */
.region-selection { position: absolute; pointer-events: none; border: 2px solid var(--el-color-danger); background: rgba(245, 63, 63, 0.14); box-sizing: border-box; border-radius: 2px; }
.region-chip { position: absolute; z-index: 3; display: inline-flex; line-height: 1; }
.region-chip :deep(.recognize-chip) { font-weight: 600; box-shadow: 0 4px 16px rgba(16, 60, 54, 0.4); border: 1px solid rgba(255, 255, 255, 0.85); }
/* 悬浮结果窗：Teleport 到 body，脱离图片滚动容器，绝不被边界挤压。 */
.region-panel { position: fixed; z-index: 3000; display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; background: #fff; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; box-shadow: 0 14px 44px rgba(16, 60, 54, 0.26); cursor: default; box-sizing: border-box; overflow-y: auto; }
.region-panel > * { flex-shrink: 0; }
.date-suggestions { border-top: 1px solid var(--el-border-color-lighter); padding-top: 8px; }
.date-suggestions > strong { font-size: 13px; }
.date-suggestions > p { margin: 4px 0 8px; }
.date-suggestion + .date-suggestion { margin-top: 8px; }
.date-suggestion-source { display: block; font-size: 12px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.date-suggestion-actions { display: flex; gap: 8px; align-items: center; margin-top: 4px; }
.date-suggestion-actions input { flex: 1; min-width: 0; padding: 4px 8px; font: inherit; font-size: 13px; border: 1px solid var(--el-border-color); border-radius: 4px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); }
.region-panel-head { display: flex; align-items: center; gap: 8px; cursor: move; user-select: none; touch-action: none; }
.region-panel-head strong { flex: 1; font-size: 13px; }
.region-panel-close { flex: none; border: 0; background: transparent; font-size: 18px; line-height: 1; color: var(--el-text-color-secondary); cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.region-panel-close:hover { background: var(--el-fill-color-light); color: var(--el-text-color-primary); }
.region-panel-foot { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.region-panel-note { margin: 0; font-size: 12px; color: var(--el-text-color-secondary); flex: 1; }
.region-error { margin-top: 12px; }
/* 影院模式：还原“点击查看原图”的全屏大图观感，识别控件弱化为暗色背景上的浮动条。
   作用域挂在 modal-class 上（本版本 el-dialog 不透传 class，mask 是对话框的稳定祖先）。 */
:global(.region-cinema-mask) { background: rgba(0, 0, 0, 0.82); }
:global(.region-cinema-mask .el-dialog) { background: transparent; box-shadow: none; overflow: visible; }
:global(.region-cinema-mask .el-dialog__header),
:global(.region-cinema-mask .el-dialog__footer) { display: none; }
:global(.region-cinema-mask .el-dialog__body) { position: relative; height: 100dvh; padding: 0; overflow: hidden; }
.region-cinema-bar { position: absolute; top: 0; right: 0; left: 0; z-index: 5; margin: 0; padding: 12px 18px 20px; background: linear-gradient(rgba(0, 0, 0, 0.62), rgba(0, 0, 0, 0)); }
.region-cinema-bar > span { color: rgba(255, 255, 255, 0.92); }
.region-cinema-bar .zoom-hint { color: rgba(255, 255, 255, 0.75); }
.region-stage-holder.is-cinema { height: 100dvh; }
.region-error.is-cinema { position: absolute; bottom: 28px; left: 50%; z-index: 6; margin: 0; transform: translateX(-50%); max-width: min(720px, 92vw); }
/* 影院模式右上角退出：沿用全屏查看器的圆形叉叉习惯位置。 */
.region-cinema-close { position: absolute; top: 14px; right: 18px; z-index: 6; width: 40px; height: 40px; border: 0; border-radius: 50%; background: rgba(43, 43, 43, 0.72); color: #fff; font-size: 26px; line-height: 1; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0 0 4px; }
.region-cinema-close:hover { background: rgba(43, 43, 43, 0.92); }
:global(.region-cinema-mask) { background: rgba(0, 0, 0, 0.82); }
</style>
