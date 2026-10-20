# Agent Note: Trim standing batch board hints to the on-demand guides

Status: implemented
Scope: frontend/src/components/BatchBoard.vue, frontend/src/components/UploadPanel.vue, frontend/src/presentation.ts, frontend/tests/presentation.test.ts
Last-verified: 2026-10-20

## Problem

The batch board showed standing hint sentences around every batch: a board-level "展开批次查看文件…" line, a fair-queue explanation whenever anything was queued, a per-package pairing explanation, a required-toolbar sentence pair ("完整表格可直接导出…／补齐并保存…筛选不改变…"), and a natural-order line above every task table. The upload panel repeated the pattern with a mode-bar hint and a three-sentence mixed-upload alert. Operators re-read the same teaching text on every visit and inside every expanded batch; the user asked to delete the useless descriptions (2026-10-20), the batch area first.

## Decision

Delete the standing lines; their knowledge stays reachable where it is actionable. The batches/batch/package/upload guides already carry each topic on demand (batch-list, batch-filter, batch-tasks, package-pairing, upload-mode steps in guide.ts), row tags show per-task export state, and the QUEUED progress tooltip keeps `fairQueueHint` (the presentation.ts export, its tooltip use and its test pins are untouched). Guide anchors move rather than disappear, honoring the guide.test.ts anchor-existence scan: `data-guide="batch-list"` now sits on a new wrapper div (`.batch-list-area`) around the empty state and the batch collapse so the anchor exists in both list states; `data-guide="batch-tasks"` moves to the el-table opening tag (Element Plus single-root attr fallthrough). The mixed-upload alert compresses from three sentences to two while keeping every caution, including the sample-qualification clause that the help manual person-package chapter promises the upload page displays. Code orphaned by the deletions is removed with the lines: the `hasQueuedTasks` computed, the `fairQueueHint` import in BatchBoard, and the `.guide-batch-hint` / `.mode-hint` style rules. Transient functional states (loading, polling tags, last-checked time, empty-state descriptions, confirm dialogs) are kept.

A same-day follow-up trimmed the batch title meta line the user quoted. The 待核对 count moves from the meta line into the existing entryNeedsReview warning tag (「待核对 N」, matching the missing-required/disputed count tags). created_at renders at minute precision without the （UTC+8） suffix — the calendar guide step and the range suffix already state the timezone, and minute precision matches the unnamed-batch title fallback. `expiryText` returns date-only 「YYYY-MM-DD 到期清理」 — the help manual already says 批次会显示到期清理日期 — and drops the 最近材料 prefix. The owner line renders only for admins: operator/viewer lists only ever contain their own batches (account-owned isolation), so the line was self-referential there; `batchOwnerLabel` itself and its test pins are unchanged. The same batch syncs every piece of pinned copy that promised the annotation to all roles: the batches guide step now reads 管理员能看到全部批次并标注每批的上传账号, help chapter 2 marks the annotation 仅管理员可见 with chapter 9's admin-context sentence qualified, and FRONTEND_FIELDS.md states the annotation row is admin-only.

## Alternatives considered

- Shorten each standing line instead of deleting it: still occupies permanent space and duplicates the guide steps word-for-word; deletion is the actual request.
- Move the lines into hover tooltips on nearby controls: adds a second on-demand layer beside the existing guide system; the guide steps already are that layer, and the fair-queue text already lives in the exact tooltip of the rows it describes.
- Keep the fair-queue line only while tasks are queued (its old v-if): still repeats during busy stretches when the board is watched most.

## Verification

vue-tsc --noEmit exit 0; the full frontend suite passes 306/306 including the guide anchor scan over all templates; vite build exits 0 with the known large-chunk warning. An adversarial three-dimension review (correctness/contract/test-quality, each finding refuted by an independent verifier) confirmed one contract defect: the first compression had dropped the sample-qualification clause promised by the help manual; the clause was restored before committing, and the other two dimensions returned no findings. The follow-up's adversarial review confirmed two defects, both fixed before committing: the collapse-all stale-expanded no-op (recorded in the [collapse-all note](../../implemented/feature/2026-10-20-batch-collapse-all.md)) and the unsynced owner-visibility copy above. Gates rerun green after the fixes: vue-tsc 0, 307/307 with the updated expiryText expectation and the new expandedNames regression, build exit 0 (also refreshing the served help copy), root verify green. frontend/public/help/index.html keeps its fuller manual text deliberately (the manual is the detailed surface) and its natural-order chapter describes behavior, which is unchanged.

## Consequences

The board and every expanded batch lose five standing sentences; first-visit orientation now leans on the guide buttons (OperationGuide), row tags and tooltips. No API, schema, recognition, backend or Mac online change. If a future step needs one of these explanations permanently again, restore it as a guide step or tooltip rather than a standing line.

## Related note audit

- [Expanded toolbar one row](../../implemented/feature/2026-10-16-batch-expanded-toolbar-one-row.md) owns the required-toolbar layout; its standing explanation span is removed while the filter tags and layout stand — refined, not replaced.
- [Natural filename order](../../implemented/bug-fix/2026-10-20-batch-task-filename-order.md) owns sorting and numbering behavior; its UI hint sentence is removed but the behavior, regressions and CHANGELOG entry stand.
- [Contextual operation guide](../../implemented/feature/2026-10-15-contextual-operation-guide.md) owns the on-demand guide system that now solely carries the deleted explanations; no decision there is superseded.
