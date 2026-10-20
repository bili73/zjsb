// 指位公共小工具：滚动到目标元素，可选交出焦点并闪烁一次。
// flash 依赖调用方模板里的 .jump-flash 样式（ReviewEditor 已内建）；不闪烁时只做滚动定位。
// 与 OperationGuide 的跳转一致：减少动态偏好下不平滑滚动（CSS 媒体查询管不到 JS scrollIntoView）。
export function revealAnchor(el: HTMLElement | null, options: { block?: ScrollLogicalPosition; flash?: boolean } = {}) {
  if (!el) return
  const { block = 'center', flash = true } = options
  el.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block })
  if (!flash) return
  // 把焦点交给目标条目：否则焦点留在已滚出视口的触发按钮上，键盘用户下一次 Tab 会把滚动拉回、指位被撤销。
  el.tabIndex = -1
  el.focus({ preventScroll: true })
  el.classList.remove('jump-flash')
  void el.offsetWidth
  el.classList.add('jump-flash')
}
