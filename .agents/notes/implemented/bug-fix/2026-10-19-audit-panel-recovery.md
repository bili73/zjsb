# Agent Note: Audit panel failure recovery and honest export confirmation

Status: implemented
Scope: frontend/src/components/AuditPanel.vue, frontend/src/components/UploadPanel.vue, frontend/src/audit.ts, frontend/tests/audit-panel-recovery.test.ts
Last-verified: 2026-10-19

Frontend-only batch unlocked by the backend's audit error-code decisions ([audit query error codes](./2026-10-19-audit-query-error-codes.md)); landed after their commit 42376fc on a clean tree.

## Problem

- Mount chained `/admin/audit/options` → first page: one options failure cancelled the list load too, a single alert covered both, and the only recovery was remounting the tab (three filter dropdowns stayed empty; an account created during the session never appeared until remount).
- `failed()` discarded error_id and retryAfterSeconds: SERVICE_BUSY with Retry-After showed static copy with no retry seconds, unlike TaskResultDrawer/ExportControls/LoginGate.
- `download()` exported the live control values while the table showed the applied snapshot; editing filters without re-querying silently changed the export predicate. Export success had no feedback; the error alert could not be dismissed.
- UploadPanel's static tip advertised PDF for every type although bank card and table reject PDF at selection time (visual audit #16 remainder).

## Decision

- Options load independently with their own loading/error state and a 重新加载筛选项 retry (options GET is idempotent per the backend note); the first page always fires. The retry stays mounted while in flight — optionsError clears only on success, so the alert containing the loading button never unmounts mid-retry.
- `failed()` mirrors TaskResultDrawer's saveReview suffix: with retryAfterSeconds show 可在 N 秒后重试, else append （错误编号 …）. Display-only; no automatic retry of anything (contract). AUDIT_FILTER_INVALID / AUDIT_EXPORT_TOO_LARGE render through the backend-landed diagnostics.ts copy; raw server messages stay discarded.
- New `auditExportDiverged(live, applied)` in audit.ts (both sides built by the same `filters()`, key order fixed, whole-JSON compare). `download()` asks a confirm dialog only on divergence (仍按当前筛选导出 / 返回检查); export then still uses live filters, matching the dialog wording. Success shows ElMessage.success; the catch gains fetchPage's revision guard so a stale export error cannot overwrite a newer query's state. The error alert is closable, and the table's empty text keys off a separate `listFailed` flag so dismissing the alert cannot flip a never-completed query into 「没有符合条件的操作记录」.
- UploadPanel's tip is type-aware via a photoOnly computed (single-type TABLE/BANK_CARD → photos only); mixed mode keeps the full-format line since per-file interception already names the offender.
- Verified-and-closed audit items #6 (ResultView medical grade/diagnosis empty → —), #20 (RetentionSettings assessed_at null → 影响数量尚未统计), #21 (TableReview merge disabled below 2 cells with tooltip): all landed by batches A/B; only the parked list was stale.

## Alternatives considered

- One retry button rerunning the whole mount chain: rejected — re-conflates two independent failures; scoped retry keeps each failure's blast radius to its own UI.
- Export the applied snapshot instead of live filters: rejected — silently ignores the operator's edits; the confirm keeps live semantics but makes divergence visible. No total-based export pre-disabling either (a displayed total is not a guarantee for a later export request, per the backend note).
- Parse server messages to split the five AUDIT_FILTER_INVALID semantics: rejected — contradicts the safe-message contract landed the same day; merged copy plus error_id is the agreed presentation.
- Disable the three selects while options load: skipped — empty placeholders plus the warning alert already communicate it; less state to keep honest.

## Verification

vue-tsc clean; 275/275 frontend tests pass. New audit-panel-recovery.test.ts (component-mount harness from detail-loading.test.ts) covers the divergence pure cases, an options failure not blocking the first page plus retry recovery, SERVICE_BUSY retry-seconds and AUDIT_EXPORT_TOO_LARGE error-id suffixes, divergence confirm cancel/honour/no-dialog-when-consistent, a 401 routing to exactly one unauthorized event, and an export still in flight at unmount never downloading or reporting success. Production build exit 0 (chunk-size warning is the known noise); root npm run verify green with this note. Pre-commit, a 3-dimension adversarial review workflow (correctness/contract/test-quality, 8 agents, each finding refuted by an independent verifier) confirmed 4 findings, all fixed in this batch: the closable-alert empty-text flip (listFailed decoupling), the structurally unpaintable retry loading state (optionsError now clears on success only), zero coverage of the 401 route, and zero coverage of unmount-mid-export (the last two became the new tests). A fifth finding (cumulative stub counters) was refuted as arithmetically unable to mask a regression and left as is.

## Consequences

- An options failure leaves the list usable (date/batch still filter) and recoverable in place; retrying also surfaces accounts created during the session.
- Rate-limited or busy audit reads show the same retry-seconds/error-id presentation as the review/export/login surfaces.
- Editing filters without re-querying and then exporting now gets an explicit choice instead of a silently different predicate; export success is visible; dismissing the error alert no longer rewrites the empty-table verdict.
- Bank card / table upload tips no longer advertise PDF; mixed mode is unchanged.
- #6/#20/#21 closed as verified-landed. Still parked: #14 remainder, #18, and the auditDetail dead path (product decision). #17 (help TOC groups) landed 2026-10-20 — [help TOC note](./2026-10-20-help-toc-groups.md).
