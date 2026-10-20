# Agent Note: Review usability fixes from the 2026-10-18 visual audit

Status: implemented
Scope: frontend/src/components/ReviewEditor.vue, frontend/src/components/ResultView.vue, frontend/src/components/UploadPanel.vue
Last-verified: 2026-10-18

## Problem

A PM-perspective visual audit of the workbench (2026-10-18) surfaced high-priority usability gaps around the review flow:

- Field-level review issues that cannot be one-click accepted (`canAcceptIssue` false — validation failures, conflicts) were only spelled out in the drawer's top red notice. A long form gave no clue which input to fix; the operator had to mentally match notice text to fields.
- Empty medical results rendered as blank cells in the items table, indistinguishable from a rendering gap; the fix entry point (edit) sat behind the drawer's 编辑 toggle with no hint anything was missing.
- The 报告等级 / 诊断 column printed 等级未识别 / 诊断未识别 on every empty row, drowning the rows that actually carry values.
- The household-register members collapse started closed with a bare 户口本成员（N 人） title; when a member's required fields came back empty, nothing on the collapsed header suggested it — inviting a "nothing recognized" misread.
- Generic key-value delete had no confirmation, although a deleted pair can only be restored by retyping it.
- save() failures surfaced one generic 请检查填写内容后重试 regardless of which section was wrong (mask submission, invalid new item, member source page, summary/coverage sections unacknowledged).
- UploadPanel's submit button stayed clickable with zero files selected and rendered an empty （） count suffix.

## Decision

- ResultView and ReviewEditor now render each non-acceptable field-level review issue as an inline red line under its field (role="status"), in both the read view and the editor, so the top notice, the read table and the edit form tell one story. Issues that ARE one-click acceptable stay out of the way (they are handled by the save flow's accepted_issues).
- Medical items table: an empty `result_raw` renders a red 未填写 marker; the 报告等级 / 诊断 column renders — when both values are empty (placeholders removed, real values keep their lines).
- Household members collapse (ReviewEditor): the title carries 户口本成员（N 人[, X 人必填缺失]） or 户口本成员（未识别到成员）; the panel auto-expands when any saved member misses a required field. Required member keys follow the `members.*` entries of `required_field_keys` via `memberFieldRequired` (backend writes the prefix, required_fields.py), legacy default being name-only.
- Generic key-value delete is a danger link button that asks for confirmation (ElMessageBox.confirm) before splicing the draft pair.
- ReviewEditor's save catch maps known error codes to pointed messages: MASKED_VALUE (未改的掩码将跳过…), INVALID_ITEM (新增检测项目需要名称和结果), MEMBER_SOURCE (姓名 + 原件页范围), SUMMARY (展开清单声明数勾选修正并填写理由), COVERAGE (勾选全部页面并填写依据); anything else keeps the generic retry line.
- ResultView's locate guard now also allows HOUSEHOLD_REGISTER (was medical-only plus BANK_CARD/INTERVIEW_FORM).
- UploadPanel submit is disabled until files are selected; the count suffix （N） renders only when N > 0.

## Alternatives considered

- Surface field issues as a red border only (no text): rejected — the border pattern already means "required and empty" for member fields; overloading it for validation conflicts would conflate two different remedies (fill in vs. compare with the original).
- Auto-expand the household panel unconditionally: rejected — for clean results it pushes 补录遗漏成员 and 全页覆盖确认 below the fold for no reason; the summary in the title is enough to invite opening when needed.
- Remove the 未填写 marker and rely on the top notice: rejected — the audit showed operators scan the table, not the notice; the marker is what makes an empty cell actionable.
- Also add HOUSEHOLD_REGISTER to TaskResultDrawer's locate allowlist so 查看来源 works inside the drawer: intentionally NOT done here — that file carries the backend agent's in-flight uncommitted feature work and stays out of this batch. Reported to the backend agent; without it, household source clicks inside the drawer are dropped (the ResultView-side guard is ready).

## Verification

Frontend typecheck, node tests (246 pass) and production build pass; `npm run verify` passes with this note. Screenshot harness (tmp/ux-audit) re-rendered all 15 screens without page errors; visually confirmed: inline red issue lines under 身份证号 in both the drawer read view and the editor, 尿糖 未填写 red marker, — in the empty grade/diagnosis column, household header 户口本成员（2 人，1 人必填缺失） auto-expanded with the missing input red-bordered, upload submit disabled at 0 files with no empty parentheses.

## Consequences

- Operators now see field-level blockers at the point of correction, which should cut the "read the top notice, then hunt for the field" loop; the top notice stays as the summary (it is the drawer-level NEED_REVIEW rendering and remains the only place listing task-level issues).
- The medical table is quieter (no per-row 等级未识别 spam) but missing results are now louder (red 未填写). Rows whose grade/diagnosis is genuinely absent read as — instead of prose; the 判定 tag still carries the abnormality state.
- Household results with missing required member fields open expanded by default; on a clean result nothing changes except the title now always shows the member count.
- Generic pair deletion now costs one confirmation click; accidental data loss in the draft is prevented, but the confirm does not protect against closing the drawer without saving (that remains dirty-state-discarded as before).
- Save failures use the [save-failure locate mechanism](../bug-fix/2026-10-20-save-failure-locate.md) to open the error panel and scroll to its anchor; the [expanded-layout correction](../bug-fix/2026-10-20-save-locate-expanded-layout.md) waits for long panels to finish expanding.
- Upload submit being disabled at 0 files changes no API behavior; the empty-parens cleanup is cosmetic.
