# Agent Note: Review usability fixes from the 2026-10-18 visual audit (batch B)

Status: implemented
Scope: frontend/src/components/TableReview.vue, frontend/src/components/AccountManagement.vue, frontend/src/components/ReviewEditor.vue, frontend/src/components/RequiredFieldSettings.vue, frontend/src/components/RetentionSettings.vue, frontend/src/components/UploadPanel.vue
Last-verified: 2026-10-18

Second slice of the 2026-10-18 visual audit, following 2026-10-18-review-usability-fixes (batch A, same audit).

## Problem

- TableReview dead end: `tableDraft` pre-fills the title suggestion and header-row suggestion into a NEW draft, but `edited` compared the draft against that pre-filled initial state, so 保存表格修正 stayed disabled until the operator touched something — the adopted suggestion could never be saved without a gratuitous edit, and nothing explained the grey button.
- The 表外识别到文字 alert demanded 「请核对是否需要补成一行」 with no action affordance.
- The merge control defaulted to a 1×1 range (self-merge); clicking it surfaced the confusing 合并范围越界 error instead of doing nothing meaningful.
- AccountManagement: protected accounts showed a red-but-dead 删除 (and greyed 禁用) with the only explanation in 12px text at the page bottom; 修改密码/重置密码 share one style with two different semantics; creating an administrator — the highest-privilege action on the page — had no confirmation while disable/delete both do.
- Medical ReviewEditor collapse bars (检测项目/清单/声明数) carried no counts, hiding the review's primary objects.
- RequiredFieldSettings crammed five concepts into one 90-character intro with 条件必填 unexplained; RetentionSettings rendered 统计于 —（UTC+8） (em dash reads like 一) when assessed_at is null.
- UploadPanel's 仅整理异常与待判定项 switch showed with zero files and carried developer phrasing (不承诺加速); bank-card PDF rejection only surfaced at submit time via a toast.

## Decision

- TableReview: save is enabled while the table has never been saved (`reviewed_tables` empty) even with zero edits, so pre-fills can be committed as-is; the alert chain gains two info states — pre-filled-not-saved (fresh) and no-modification-with-red-frames (saved but export-blocked). The merge button is disabled (with tooltip) until the range covers ≥ 2 cells; validateGrid stays as the backstop. Each 表外文字 snippet gets a 补为末行 button that appends a row via `editAxis(draft,'row',rows.length)` with the snippet text in the first cell, then marks the snippet 已补为末行 (draft-level; still saved only via 保存).
- AccountManagement: `protectionReason` derives the per-row disable reason (当前登录账号 / 最后一个启用的管理员), shown as tooltips on the disabled 禁用/删除 buttons; password buttons get semantic tooltips (自己=需当前密码, 他人=旧登录全部失效); creating an admin role asks ElMessageBox.confirm listing the admin powers before calling createUser.
- ReviewEditor: medical collapse titles become 编辑检测项目 / 增删项目（N 项：X 项异常、Y 项待判定[, 另新增 n]） from `result.stats` (same numbers as the stat cards), 编辑报告检查治疗清单（N 条）, and 清单声明数 / 增删条目（声明 X） with 数量未声明 fallback.
- RequiredFieldSettings: intro split into 自定义/恢复默认 sentences including 条件必填 mention; tooltips on 全选可填写项/清空选择/恢复默认/重新读取 state each button's exact effect. RetentionSettings: 重新读取 tooltip; assessed_at null now renders 影响数量尚未统计 instead of the dash+（UTC+8） hybrid.
- UploadPanel: bank-card PDF rejection moved into `invalidReason` (fires on file selection, both single-type and mixed via the per-row classified type; named file in mixed mode) — the submit-time toast stays as backstop; the medical switch row renders only once files are selected and the hint now reads 只改变默认显示的项目范围；核对和导出仍按完整结果检查 (speed claim dropped entirely rather than reworded).
- Editor link affordance (audit item 7, decided after user delegation): the five gray `link` buttons in ReviewEditor (查看来源, 查看来源 / 整页, 检测行来源, 诊断来源, 清单来源) and ResultView's 诊断来源 gain `type="primary"`, so clickable links read as links instead of captions. The section-wide bold is deliberately KEPT as-is: it was the user's explicit two-step request (section text bold, then data inputs bold), and with links in primary blue the caption-vs-link confusion is resolved; shrinking label weight would walk back the requested prominence.

## Alternatives considered

- Make `edited` itself true for fresh tables: rejected — it would flip the drawer's dirty flag on open and nag on close; gating only the save button expresses "this is saveable" without claiming "you changed something".
- Append outside text into the selected cell instead of a new row: rejected — the alert says 补成一行; landing it in a fresh row matches the requirement and the operator can cut/paste inside the grid afterwards.
- Confirm dialog on 清空选择: rejected as over-confirming; the existing empty-selection warning alert already fires when the count hits zero, and the new tooltip states the save consequence up front.
- Reword 不承诺加速 to 不会更快: rejected — both phrasings answer a question nobody asked mid-upload; the hint now states what the switch does and leaves speed unmentioned (no new claims introduced).

## Verification

Frontend typecheck, node tests (246 pass) and production build pass; `npm run verify` passes with both notes. Screenshot harness re-rendered all 15 screens without page errors; visually confirmed: table page shows the pre-fill info alert with an ENABLED save button, 补为末行 button on the outside-text row, disabled 合并 at the 1×1 default; medical editor collapse titles carry （4 项：2 项异常、2 项待判定）/（2 条）/（声明 2）; upload page no longer shows the medical switch with zero files.

## Consequences

- A fresh table can now be exported after one explicit save with no edits — that save is what makes export_ready true; operators who re-open a previously saved table see the old behavior unchanged (edited-gated save).
- 表外文字 appending mutates only the draft; nothing reaches the backend until 保存表格修正, and the appended row counts against the grid limits (validated by editAxis).
- Admin creation now costs one confirmation click; the dialog enumerates powers, which doubles as the protection rule visibility fix alongside per-row tooltips.
- The retention line no longer renders a dash that reads as 一; pages where statistics are pending say so in words.
- The medical switch appearing late means an operator cannot pre-set it before adding files; acceptable because it is a display default, not an upload parameter they must plan ahead for.
- Batch B does NOT touch: the audit page findings (detail-drawer idleness, export-vs-snapshot divergence — backend coordination), the terminology sweep and remaining low items in backend-entangled files (presentation.ts/BatchBoard/help index.html carry the backend agent's uncommitted feature work; deferred to the same surgical-commit flow after their feature lands). The editor bold/links question is resolved above (bold kept, links primary).
