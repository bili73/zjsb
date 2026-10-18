# Agent Note: Trace account and material operations through administrator audit

Status: implemented
Scope: backend/ocr_app, backend/migrations, frontend/src, frontend/public/help, tests, frontend/tests, SPEC.md, openapi.yaml, RUNTIME.md, FRONTEND_FIELDS.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, scripts/probe_operation_audit_browser.cjs
Last-verified: 2026-10-16

## Problem

The shared workbench has task audit rows and encrypted review revisions but no administrator history UI. Account/session changes and failed requests are not covered. Existing export_full rows are written before workbook generation, so they cannot prove a generated or downloaded file. The user approves the proposed audit scope on 2026-10-16.

## Decision

The event scope, per-material granularity and review comparison UI below are partially superseded by the approved [concise account actions decision](../../implemented/simplification/2026-10-16-account-action-audit.md). Identity, transaction, permission and migration decisions remain applicable.

Extend the existing SQLite audit table additively. Preserve every legacy row and mark its outcome as legacy/unknown rather than inventing success or historical names. New rows retain actor UUID, encrypted identity snapshot and connection context, immutable object IDs, event/result, UTC timestamp, request ID and value-free details. User-visible timestamps use UTC+8. Never log passwords, session credentials, whole requests or OCR values. Review comparisons read the existing encrypted before/after artifact and disappear when material retention/deletion removes that artifact. Audit summaries and identity attribution remain independent of material retention; no automatic audit purge or mutation API is introduced.

Use a shared append function in the same transaction as successful account/task/settings mutations. Failure records use a separate transaction after business rollback. Logout revocation must not be prevented solely by failed audit writes; account disable/reset/delete remain atomic with their audit records. Record export request and generation separately; authorization is rechecked before returning generated data. Do not claim browser delivery. Capture login failure/throttling, session replacement, account lifecycle, upload/append, review, cancel/rerun/delete, source access/region OCR, export and global policy changes. Exclude polling and personal presentation clicks. Use only the observed peer IP, not forwarded headers.

An admin-only Operation Audit tab provides descending cursor pagination, date/account/event/outcome/batch filters, event details and bounded Excel export. Permission is checked on entry and after potentially slow reads. Account switching fences in-flight responses. Database backups preserve audit rows; encrypted review artifacts and the original storage key are required for detail recovery. No production migration/restart or Mac activation is implied by implementation tests.

## Related decisions

- [Account lifecycle](../../implemented/feature/2026-10-10-account-lifecycle-management.md), [account ownership](../../implemented/feature/2026-10-10-account-owned-batches.md) and [single sessions](../../implemented/feature/2026-10-12-thirty-day-single-session.md) partially overlap: retain permissions, immutable ownership, account protection and revocation; add recorded identity snapshots.
- [Authorization boundaries](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md) retains live transaction/response checks.
- [Diagnostics](../../implemented/feature/2026-10-15-error-only-chinese-diagnostics.md) remains ERROR/CRITICAL-only. Successful business audit is a separate record stream.
- [Retention](../../implemented/feature/2026-10-15-admin-file-retention.md) still governs material and review values, not audit summaries.
- Proposed/rejected notes contain no competing audit implementation. The hosted-auth proposal is unrelated to this portable business-layer feature. No note is superseded.

## Alternatives considered

- Reuse HTTP/error logs alone: requires fewer writes and already has request IDs, but cannot describe transactional success or preserve review/account attribution.
- Add an external audit service: isolates storage and could improve independent tamper resistance, but adds deployment dependencies for a small single-service installation and loses simple local atomicity.
- Copy all review values into permanent audit JSON: simplifies historical comparisons but defeats material retention and duplicates sensitive content. Reuse encrypted review artifacts instead.

## Testing

Isolated tests cover anonymous/operator/viewer denial, revoked sessions during reads, failed writes rolling back both operation and success event, post-rollback failures, logout despite isolated audit failure, deleted/renamed/recreated identities, failed workbook generation, legacy migration without rewriting rows, cursor ties, filtering/export, encrypted detail expiry and backup/restore. The 57-test authorization/migration suite, latest 37-test audit/store suite and 10 deletion tests pass. Frontend 230 tests, typecheck and isolated production build pass. The real Edge probe uses the actual Vue component with synthetic responses and zero business-service requests; four groups cover UTC+8/pagination, before/after details and closing races, filtered download and explicit query errors. Evidence is under output/operation-audit/attempt-E8mzNL/ and tmp/audit-*.log; earlier failed evidence is retained.

The final full backend regression passes 876 tests in 357.061 seconds (tmp/audit-backend-final.log). Two additional boundary tests pass (tmp/audit-boundaries.log): 10001 matching records reject export rather than truncate, and UTC+8 midnight ranges include the correct instants. DDE index/verify and diff checks pass. Earlier failed compatibility assertions expected zero failure audit rows; their replacements still require all material rows/files and existing audit records to remain unchanged and explicitly distinguish successful mutations from rejected attempts. No production activation is implied.

## Windows activation evidence

On explicit user restart authorization, activated this checkout on 2026-10-16 in dual_resident mode after confirming no queued, active or expired tasks. The consistent schema0010 SQLite backup, encrypted materials, keys and previous static files are retained under output/operation-audit-activation-20261016-103712/snapshot/. Startup applied schema0011. Verification preserved all original columns of 13 business tables, 269 tasks, 2 accounts, the existing session, 2994 legacy audit rows and 2977 material/key files; retention remains 15 days. All 16 served static files match the tested final build; the login page renders and all four new audit route shapes reject anonymous requests with 401. Evidence: output/operation-audit-activation-20261016-103712/verified.json.

Both owned model process trees exist. Authenticated model readiness and live administrator audit queries were not checked because no existing browser session was available; no account/session was created or replaced. Public health is not model readiness evidence. This is a Windows activation of the current uncommitted worktree, not a Git publication or Mac deployment.

## Consequences

Application append-only access does not prevent a server administrator editing SQLite. Peer addresses may identify a proxy instead of a device. Legacy data cannot reconstruct unrecorded account events or certify old exports. Audit storage grows independently; a retention/archive policy requires a later explicit decision.

Review comparisons include certificate fields, household members, medical items/summary, reviewed table grids/merges and generic form values, without duplicating OCR metadata into permanent audit. Account deletion during a failed request retains the last authenticated identity snapshot. schema0011 is incompatible with old positional audit INSERTs: code-only rollback is not supported; restore the verified matching database/material/key snapshot with its old code. The Windows checkout is verified independently from the Mac deployment branch.
