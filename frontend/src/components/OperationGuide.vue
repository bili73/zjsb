<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElTour, ElTourStep } from 'element-plus'
import { Guide } from '@element-plus/icons-vue'
import { findGuideTarget, guideSteps } from '../guide.ts'
import type { GuideContext, GuideStep } from '../guide.ts'

const props = withDefaults(defineProps<{
  context: GuideContext; scope: string; canWrite: boolean; isAdmin?: boolean;
  label?: string; active?: boolean; resetKey?: string
}>(), { label: '操作指引', active: true, isAdmin: false, resetKey: '' })
const open = ref(false), current = ref(0), locating = ref(false)
const steps = ref<GuideStep[]>([])
const target = shallowRef<(() => HTMLElement) | undefined>()
const available = computed(() => props.active && guideSteps(props.context, props.canWrite, props.isAdmin).length > 0)
let frame = 0, generation = 0
let trigger: HTMLElement | null = null
let outlined: HTMLElement | undefined
let glideTimer: number | undefined

function clearTarget() {
  cancelAnimationFrame(frame)
  clearTimeout(glideTimer)
  outlined?.classList.remove('operation-guide-target')
  outlined = undefined; target.value = undefined
}
function glideTo(getEl: () => HTMLElement) {
  // 面板从旧锚点滑到新锚点：仅在换锚瞬间开启过渡（is-gliding 窗口），滚动跟随期间保持即时，避免拖影。
  target.value = getEl
  const content = document.querySelector?.('.el-tour__content')
  content?.classList.add('is-gliding')
  clearTimeout(glideTimer)
  glideTimer = setTimeout(() => content?.classList.remove('is-gliding'), 340)
}
function close() {
  const wasOpen = open.value
  generation++; open.value = false; clearTarget()
  window.removeEventListener('keydown', onKey, true)
  if (wasOpen && trigger?.isConnected) trigger.focus({ preventScroll: true })
}
function onKey(event: KeyboardEvent) {
  if (locating.value && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault(); event.stopImmediatePropagation(); return
  }
  if (event.key === 'Escape') {
    // Esc must close the tour only, not the result drawer containing an unsaved draft.
    event.preventDefault(); event.stopImmediatePropagation(); close()
  }
}
async function start(event: MouseEvent) {
  if (!available.value) return
  trigger = event.currentTarget as HTMLElement
  steps.value = guideSteps(props.context, props.canWrite, props.isAdmin)
    .filter(item => !item.optional || findGuideTarget(document, props.scope, item.anchor))
  current.value = 0; open.value = true
  window.addEventListener('keydown', onKey, true)
  await nextTick(); if (open.value) locate()
}
function locate() {
  if (!open.value) return
  const run = ++generation
  locating.value = true
  const started = performance.now()
  let found: HTMLElement | undefined, previousRect = '', stableSince = started
  let resolved = false
  const tick = () => {
    if (!open.value || run !== generation) return
    const element = findGuideTarget(document, props.scope, steps.value[current.value]?.anchor ?? '')
    if (!element) {
      // 锚点被移出文档 → 立即解绑（兜底居中 + 提示）；只是暂时找不到（懒加载、未展开）→
      // 保留上一个锚点，面板不闪回屏幕中央，超过 800ms 才落兜底。
      // 两种情况都不退出循环：兜底后元素再出现，仍要能重新绑定。
      if (outlined && outlined.isConnected === false) {
        outlined.classList.remove('operation-guide-target'); outlined = undefined
        target.value = undefined; locating.value = false
      } else if (performance.now() - started > 800) {
        outlined?.classList.remove('operation-guide-target'); outlined = undefined
        target.value = undefined; locating.value = false
      }
    } else {
      if (element !== found) {
        outlined?.classList.remove('operation-guide-target'); outlined = undefined
        found = element; previousRect = ''; stableSince = performance.now()
        element.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center', inline: 'nearest' })
      }
      const rect = element.getBoundingClientRect()
      const signature = [rect.x, rect.y, rect.width, rect.height].map(value => Math.round(value)).join(',')
      if (signature !== previousRect) {
        previousRect = signature; stableSince = performance.now()
        // 已解析过的目标跟随滚动实时移动；未解析的新目标保持旧锚点，等稳定后一次滑过去。
        if (resolved && target.value) target.value = () => element
      }
      if (performance.now() - stableSince > 100 && !resolved) {
        outlined = element; element.classList.add('operation-guide-target')
        resolved = true
        glideTo(() => element)
      }
      // Let both the scrolling target and the floating panel settle before enabling navigation.
      if (resolved && performance.now() - stableSince > 250) locating.value = false
    }
    // Only runs while the short tour is open; follows nested scrolling and layout changes.
    frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)
}
watch(current, () => { if (open.value) locate() })
watch(() => [props.active, props.context, props.scope, props.resetKey, props.canWrite, props.isAdmin], close)
onBeforeUnmount(close)
</script>

<template>
  <el-button :icon="Guide" round class="operation-guide-entry" :disabled="!available" @click="start">{{ label }}</el-button>
  <ElTour v-if="open" :model-value="open" v-model:current="current" :target-area-clickable="false"
    :close-on-press-escape="false" :scroll-into-view-options="{ behavior: 'instant', block: 'nearest', inline: 'nearest' }"
    :mask="{ color: 'rgba(15, 23, 42, 0.55)' }" :gap="{ offset: 8, radius: 8 }"
    @update:model-value="value => { if (!value) close() }">
    <ElTourStep v-for="(item, index) in steps" :key="item.anchor" :title="item.title"
      :target="index === current ? target : undefined" :show-arrow="!!target" :content-style="{ width: 'min(420px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 32px)', overflowY: 'auto' }"
      :prev-button-props="{ children: '上一步', disabled: locating }" :next-button-props="{ children: index === steps.length - 1 ? '完成指引' : '下一步', disabled: locating }">
      <p class="operation-guide-copy">{{ item.text }}</p>
      <p v-if="locating" class="operation-guide-status" role="status">正在定位当前区域…</p>
      <p v-else-if="!target" class="operation-guide-status" role="status">当前没有显示这个区域。可继续阅读，或关闭指引、展开对应内容后再试。<el-button link @click="locate">重新定位</el-button></p>
      <p class="operation-guide-hint">{{ index + 1 }} / {{ steps.length }} · 按 Esc 或右上角 × 退出；不会提交或保存。</p>
    </ElTourStep>
  </ElTour>
</template>

<style>
.operation-guide-target { outline: 3px solid #ef760e !important; outline-offset: 4px; }
.operation-guide-copy { line-height: 1.8; margin: 8px 0 14px; color: var(--el-text-color-primary); }
.operation-guide-status { line-height: 1.6; color: var(--el-color-warning-dark-2); }
.operation-guide-hint { font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
/* 指引入口：主色胶囊，在工具栏里一眼可辨；经 el-button 主题变量着色，跟随主题色与禁用态。 */
.el-button.operation-guide-entry { --el-button-text-color: var(--el-color-primary); --el-button-bg-color: var(--el-color-primary-light-9); --el-button-border-color: var(--el-color-primary-light-7); font-weight: 600; padding: 8px 16px; }
.el-button.operation-guide-entry:hover, .el-button.operation-guide-entry:focus-visible { --el-button-hover-text-color: var(--el-color-primary); --el-button-hover-bg-color: var(--el-color-primary-light-8); --el-button-hover-border-color: var(--el-color-primary-light-5); }
.el-button.operation-guide-entry.is-disabled { --el-button-disabled-text-color: var(--el-text-color-placeholder); --el-button-disabled-bg-color: var(--el-fill-color-light); --el-button-disabled-border-color: var(--el-border-color-lighter); }
/* 翻步过渡：换锚瞬间（is-gliding 窗口）面板滑向新目标；蒙层是 SVG 裁剪路径，保持瞬时切换。 */
@media (prefers-reduced-motion: no-preference) {
  .el-tour__content.is-gliding { transition: top 0.3s cubic-bezier(0.3, 0.8, 0.3, 1), left 0.3s cubic-bezier(0.3, 0.8, 0.3, 1); }
  .operation-guide-target { animation: operation-guide-outline-in 0.3s ease; }
  @keyframes operation-guide-outline-in { from { outline-color: transparent; outline-offset: 18px; } }
}
</style>
