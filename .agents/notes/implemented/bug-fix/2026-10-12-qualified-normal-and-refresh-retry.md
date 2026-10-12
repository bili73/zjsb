# Agent Note: Qualify measured normal summaries and retain failed refresh work

Status: implemented
Scope: backend/ocr_app/medical_ledger.py, backend/ocr_app/exporting.py, frontend/src/monitor.ts, frontend/tests/monitor.test.ts, tests/test_medical_ledger.py, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-12

## Problem

One recognized normal row can produce a group-wide-looking 未见异常. Existing qualifications do not establish complete recognition. A completed batch refresh that fails its task-list request consumes the observed batch timestamp and the forced-refresh flag; a successful retry can skip the stale tasks and stop polling.

## Decision

The user approves 已识别明细未见异常 only for normal summaries derived from measured rows without a printed conclusion. Explicit source conclusions and manual values keep their original meaning. Read/export projections apply the rule without rewriting encrypted history. Abnormal and conflicting rows retain priority.

Track batches requiring task reconciliation until a task-list request succeeds for the captured batch metadata version. Register forced reconciliation before reading the batch list, retain pending work through network failure and pagination timestamp changes, and remove it on successful reconciliation, confirmed deletion or session reset. Keep the loop scheduled while reconciliation remains pending, including when a newer page read advances metadata during an older task read. Preserve cancellation, session-generation and permission fences.

## Decision audit

The [measured summaries](../../implemented/bug-fix/2026-10-09-medical-measured-group-summaries.md) and [review repairs](../../implemented/bug-fix/2026-10-12-review-repairs.md) partially overlap: measured inference and explicit refresh remain, while the derived wording and failure recovery change. Neither older decision is wholly superseded. No rejected clinical-grading or localization proposal is revived.

## Alternatives considered

- Keep the warning and original wording: preserves familiar display, but still presents incomplete measured evidence as an unqualified group result.
- Require a printed laboratory conclusion: offers direct quoted evidence, but the supported laboratory sections do not print conclusions.
- Retry every cached task indefinitely: avoids dropped work, but repeatedly reads/decrypts unchanged history. Retain only unresolved reconciliation plus existing live-task reads.

## Verification

Both defects reproduce before implementation; the original failed logs remain in output/pm-remediation-20261012-v1/. Regression covers partial recognized normal evidence, Excel agreement, explicit/manual conclusions, failed task reads, failed first-page reads with older cached pages and newer metadata arriving during an old task read. All615 backend tests and115 frontend tests pass; typecheck and production build pass. An isolated real-browser medical view displays the new value and qualification beside it. No production task is re-recognized for this check.

## Consequences

The [pre-push isolation repairs](2026-10-12-prepush-isolation-and-migration.md) prevent late overlapping pages from downgrading refreshed batches and wake the existing read loop for accepted new/changed page data without forcing every terminal task to reread.

The [person-name workflow](../feature/2026-10-12-person-package-name-suggestions-and-export.md) extends reconciliation with single-Batch metadata reads for older pages and task completion between list/task snapshots. Pending retry and generation/reference guards remain active; names, package revisions and pairing no longer depend only on first-page metadata.

Recognized-detail wording avoids an unqualified whole-group claim, but still cannot establish clinical fitness or report completeness. Reads can race later server changes; mutation run/revision checks remain authoritative. Pending reconciliation survives failures without polling unchanged completed history indefinitely.
