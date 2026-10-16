# Agent Note: Batch expanded toolbar consolidated to one row with exclusive filter tags

Status: implemented
Scope: frontend/src/components/BatchBoard.vue, frontend/src/components/ExportControls.vue, frontend/public/help
Last-verified: 2026-10-16

## Problem

The expanded batch header scattered actions across four stacked rows: the guide entry button on its own line, ExportControls (mode radio + 下载 Excel) on the next, an admin-only row with 删除批次 plus a standing explanation sentence, and a filter row with two independently checkable checkboxes (只看必填未填 / 只看有异议) that could be combined. The user asked for all buttons in one row with 本批次指引 and 删除批次 to the right of 下载 Excel, and for the two filters to become a mutually exclusive, differently styled control.

## Decision

- New `.batch-actions` row in BatchBoard: ExportControls first, then OperationGuide (本批次指引), then the admin 删除批次 button — one adjacent cluster in the requested order (an initial flex-spacer variant that pushed the right group to the row edge was dropped at the user's follow-up: 删除批次 must sit close to 下载 Excel). ExportControls dropped its own padding so the row container owns spacing, and the 下载 Excel button gained the Download icon matching the drawer's 导出 Excel.
- The standing 删除批次 explanation sentence is gone; the button is disabled with the reason (running / loading / no tasks) surfaced through hover tooltip, the same pattern as the disabled export buttons. Deletion consequences stay in the confirm dialog.
- Filters become `el-check-tag` chips instead of checkboxes: clicking selects and clears the sibling (mutually exclusive via `setMissingOnly`/`setDisputedOnly`), clicking again deselects back to showing all tasks. Checked chips take semantic colors matching the row markers: danger for 必填未填, warning for 有异议. `visibleTasks` keeps its OR-shape — exclusivity makes the combined state unreachable without changing the predicate.

## Alternatives considered

- el-radio-group for the filters: rejected — a radio group forces a permanent selection or needs an extra "全部" option, adding a third control; the chip's toggle-off returns to all with one click.
- Keep the delete hint as standing text: rejected — the user's direction is fewer standing sentences; the failure mode (disabled button) is transient and hover already carries the reason.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note. Guide anchors (batch-filter on the chips wrapper, batch-export inside ExportControls) were not moved, so the anchor-existence test needed no change; help page wording updated from 勾选 to 点选 for the two filters.

## Consequences

Users can no longer filter by 必填未填 AND 有异议 simultaneously — to see the union they clear one chip and read the other, or use the row highlighting (`required-missing-row`) which still marks both conditions at once. Guide entry and batch deletion now live inside the same flex row, so any future component added there must tolerate wrap at narrow widths.
