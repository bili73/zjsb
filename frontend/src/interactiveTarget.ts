// “取消定位红框”的点击目标判定：点在交互控件或页面图片上时，点击有自身语义，不算点空白。
// TaskResultDrawer（抽屉级空白清除）与 SourcePreview（原图版面空白清除）共用同一份排除规则。
export const INTERACTIVE_CLICK_SELECTOR = [
  'button', 'input', 'textarea', 'select', 'option', 'label', 'a', 'summary', '[role="button"]',
  '.el-input-number', '.el-select', '.el-checkbox', '.el-radio', '.el-switch', '.el-date-editor', '.el-cascader', '.el-tag',
  '.el-image', '.img-wrap', '.el-collapse-item__header', '.el-drawer__close-btn',
].join(', ')

export function isInteractiveClickTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(INTERACTIVE_CLICK_SELECTOR) !== null
}
