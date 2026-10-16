---
name: operation-guide
description: 页面级操作指引系统（guide.ts 步骤配置 + data-guide 锚点 + OperationGuide/ElTour 组件）—— 为页面新增或修改指引步骤、放置/调整 data-guide 锚点、排查指引不显示、框错位置、翻步跳变、Esc 穿透等问题时使用。
---

# 页面操作指引（OperationGuide）

三个文件构成系统，改任何一处都要同步其余两个：

- `frontend/src/guide.ts` —— 步骤配置的唯一来源：按 `GuideContext`（页面/材料类型）分组，每步 = `{ anchor, title, text, write?, optional? }`；`guideSteps()` 按 `canWrite`/`isAdmin` 裁剪，`findGuideTarget()` 在 `[data-guide-scope]` 内找**唯一可见**的 `[data-guide]` 元素；`detailGuideContext()` 把材料类型映射到详情页指引。
- `frontend/src/components/OperationGuide.vue` —— 挂载点组件：手动启动的 ElTour 短指引，rAF 逐帧跟踪目标滚动/布局，稳定后才启用上一步/下一步。
- 页面模板里的 `data-guide="anchor"` 锚点 + `data-guide-scope="scope"` 作用域容器。
- 契约测试 `frontend/tests/guide.test.ts`：编译真实 SFC 跑 Vue 生命周期，强制"步骤 ↔ 模板锚点"契约。

## 新增一个页面的指引（四步）

1. `guide.ts`：加 `GuideContext` 类型 + `guides[context]` 步骤数组（每页 3–6 步）。
2. 页面模板：容器加 `data-guide-scope="page-xxx"`（重复组件如批次卡用独立 scope），每个要讲的组件加 `data-guide="xxx"`。
3. 挂 `OperationGuide`：`:context` `:scope` `:label`（如"本页指引"）`:can-write` `:is-admin` `:active`（页面不可见/被抽屉遮挡时必须 false）`:reset-key`（页面标识变化时强制重置）。
4. 跑 `tests/guide.test.ts`：锚点存在性断言会强制步骤与模板一致。

## 新增/修改一步：锚点选择规则

- **锚点框住组件，不框整行**（用户明确要求过）：`data-guide` 放在按钮、输入框、单选组、控件组包裹层上；多个控件作为一个单位讲时，用 `inline-flex; gap` 的轻量 `<span>` 包一层作锚点（参考 BatchBoard 的 `.calendar-controls`/`.board-actions`/`.filter-checks`、ExportControls 的 `.export-actions`）。
- 文案与锚点一致：文字只讲框住的控件；讲了别的控件就把锚点上移到控件组，不要框整行。
- 步骤文案必须声明"指引不会替你提交/保存"，禁止用业务动作（点按钮、切开关）去揭示目标——只滚动和讲解。
- 条件渲染的步骤标 `optional: true`（start 时按当前可见性过滤）；只读账号可见性不同的内容用 `write: true`（guideSteps 自动剔除并按需追加只读版文案）；管理员专属上下文（accounts/required/retention）非管理员返回空数组。

## 机制与铁律（违反会复现修过的故障）

1. **翻步不闪回屏幕中央**：ElTour 对无 target 的面板用 `top:50%/left:50%` 居中，翻步定位期间若把 target 置 undefined，面板会先闪到中央再跳到新目标。定位不到时**保留上一个锚点**，超过 800ms 才落兜底（居中 + "当前没有显示这个区域"提示）。
2. **锚点被移出文档（isConnected=false）→ 立即解绑**；"暂时找不到"（懒加载/未展开）→ 保留锚点等待。两者用 isConnected 区分。
3. **800ms 兜底后不能退出 rAF 循环**：循环是后续重新绑定的机制，提前 return 会让元素再出现时永远绑不上（真实事故）。循环只在 `!open || run !== generation` 时退出。
4. **滑动过渡用 is-gliding 窗口**：换锚瞬间给 `.el-tour__content` 加 `transition: top/left`，滚动跟随期间不加（否则面板拖尾 300ms）。用 `glideTo()` 统一管理。
5. **Esc 只关指引**：window 捕获阶段监听 + `stopImmediatePropagation()`，防止穿透关闭含未保存草稿的结果抽屉；关闭后焦点还给触发按钮。
6. **指引无业务副作用**：不提交、不保存、不重跑、不删除、不切换模式；`target-area-clickable=false` + 焦点陷阱保护业务区域。
7. **Node 单测环境守卫**：测试用假 document/window（只有 addEventListener/querySelectorAll 等被测方法），组件代码里禁止 `window.setTimeout`（用裸 `setTimeout`）、`document.querySelector` 要可选调用（`querySelector?.()`）。
8. **改按钮必须同步**：挪动/删除带 `data-guide` 的元素时，同步改 guide.ts 步骤与文案，并跑 guide.test.ts（锚点存在性断言会拦住漏改）。

## 验证配方

1. `node --test tests/guide.test.ts`：7 个契约测试（锚点存在、作用域隔离、晚到目标、滚动跟随、换步去高亮、Esc 阻断、卸载清理）必须全过。
2. 浏览器走查（临时 harness：一个 tall 页面放 3 个纵向+横向错开的 `data-guide` 锚点 + 挂组件）：开指引 → 逐步下一步 → 采样 `.el-tour__content` 中心点，断言出现多个中间位置（滑动而非跳变）且不落在视口正中（旧实现会精确停在中心）→ 外框 `data-guide` 落在正确元素 → Esc 关闭无残留高亮。
3. 改动后全套门禁：typecheck + 全部测试 + build（无条件执行）+ verify。

## 相关笔记

设计与边界详见 `.agents/notes/implemented/feature/2026-10-15-contextual-operation-guide.md`（含手册整合、权限裁剪、无首登强制指引等决策）。
