# Agent Note: Revalidate settings writes and reconcile cross-session batch changes

Status: implemented
Scope: backend/ocr_app/required_fields.py, backend/ocr_app/routes.py, backend/ocr_app/exporting.py, tests/test_required_field_settings.py, tests/test_medical_ledger.py, frontend/src/business.ts, frontend/src/monitor.ts, frontend/src/App.vue, frontend/src/components/BatchBoard.vue, frontend/src/components/ResultView.vue, frontend/src/components/TaskResultDrawer.vue, frontend/tests, SPEC.md, openapi.yaml, IMPLEMENTATION_PLAN.md, frontend/public/help/index.html, RUNTIME.md
Last-verified: 2026-10-12

## Problem

The user authorizes fixing the review findings in priority order. A streamed settings request authenticated before account disabling still commits after session revocation. A batch deleted from another session remains cached and its 404 stops unrelated task polling. Completed task snapshots survive manual refresh even after another session reviews them, so version-bound export, deletion and rerun remain conflicted. Rerun also clears the current result without confirmation.

## Decision

Require an authorization callback for save_configuration and execute it inside BEGIN IMMEDIATE before reading or changing policy, including no-op saves. The HTTP route supplies the existing live administrator-session check; trusted internal test callers explicitly supply their authorization callback. Keep Origin, CSRF, policy revision, field validation and audit behavior.

Handle task-list 404 at the individual batch boundary. Remove only that confirmed inaccessible batch, its pending operations and local previews, and close its result drawer. Continue other jobs and reconcile totals on the next list read. A missing first-page ID is never sufficient evidence of deletion because pagination and date filtering intentionally retain hidden jobs. Preserve generation and abort fences before handling late failures.

Manual refresh, visibility refresh and post-action reconciliation reread loaded task snapshots, including older pages. Automatic polling refreshes running batches and batches whose status, update timestamp or shared required-fields revision changes. Reflect actual polling termination in the UI. Do not introduce push subscriptions or a cache persistence layer.

Add an explicit rerun confirmation naming the file and explaining that the current result and manual corrections cease to be the displayed version; recommend exporting any result the user needs to retain. On 2026-10-12 the user selects confirmation/export guidance without history restoration, retention of the medical derivation rule with an explicit recognized-detail limitation, and retention of single-type batches with planned completeness/append capabilities clearly marked unimplemented. Put the medical limitation beside result fields and in XLSX comments on normal summaries derived from detail rows; do not alter values, columns, manual conclusions or source conclusions. Correct demonstrably stale account-management documentation without claiming new accuracy measurements.

Browser acceptance at 1280px exposes an existing responsive-layout conflict: the inline three-column grid overrides the narrow-screen single-column rule while the splitter is hidden, leaving the result pane 6px wide. Pass only the draggable left width as a CSS custom property so the media rule can select one column. Keep desktop resizing and the existing breakpoint.

## Decision audit

- [Shared required fields](../../implemented/feature/2026-10-10-configurable-required-fields.md) and [account lifecycle](../../implemented/feature/2026-10-10-account-lifecycle-management.md) partly overlap: preserve their policy and session contracts while extending transactional authorization to settings.
- [Account-owned batches](../../implemented/feature/2026-10-10-account-owned-batches.md), [batch deletion](../../implemented/feature/2026-10-10-delete-recognized-batches.md), [calendar browsing](../../implemented/feature/2026-10-09-batch-calendar-browser.md) and [frontend workbench](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partly overlap: retain ownership, pagination and hidden running jobs, and repair cross-session invalidation.
- [Measured medical group summaries](2026-10-09-medical-measured-group-summaries.md) partly overlaps: retain the explicitly selected derivation and normal values, and qualify their recognized-detail scope in the UI and Excel comments.
- Proposed hosted authentication/Mac deployment and rejected clinical grading or certificate localization do not own these local correctness fixes. No existing decision is wholly superseded or archived.

## Alternatives considered

- Authenticate only once at request entry: simple and customary for short requests, but request-body streaming can keep an already revoked administrator authorized indefinitely. Revalidate at the write transaction boundary.
- Clear every batch absent from page one: immediately removes deleted cards with no extra requests, but also removes legitimate older pages and tasks outside the current date range. Remove a batch only on its own 404.
- Reread every historical task every two seconds: provides broad cross-session freshness, but repeatedly decrypts unrelated historical results. Force full cached-task refresh for explicit reconciliation and otherwise use existing status/timestamp/policy signals.
- Build full history restoration now: provides stronger recovery, but needs a durable version-selection and permission contract beyond the immediate accidental-rerun fix. First add informed confirmation without promising recovery.

## Verification

The streamed-body HTTP regression fails before the fix with HTTP200 after account disable or logout; it now returns401 without policy/audit changes, including a no-op save. Three frontend regressions fail before the fix for remote deletion and manual/terminal refresh. The passing monitor tests cover continuing peer jobs, retained older pages, reset pagination, task removal callbacks, revision freshness and late old-session404 fences. Excel regression first fails for the absent comment, then verifies its presence without changing values, source conclusions, manual conclusions or input results.

The full backend regression passes563 tests in197.632s; all107 frontend tests and typecheck/build pass. Relevant settings tests pass9 and medical/workbook tests pass25. Browser acceptance uses a separate encrypted synthetic store and FakeRuntime, without production writes or real model inference. Cancelling rerun retains revision1, the original result and one run; confirmation creates exactly one additional run, advances to revision2/QUEUED and clears the current result. The medical summary qualification renders beside its fields. At1280px the result pane is1097px wide rather than6px; at1440px the two panes are496px and723px, dragging changes the left width to575px and double-click restores496px. Browser console error count is zero. Screenshots, cancellation/confirmation measurements and the interrupted probe's data remain under tmp/review-repairs-ui-20261012. The isolated server resumes the same store after interruption, without reseeding it.

## Consequences

Explicit refresh makes one task-list request per cached batch. The server remains authoritative and changes after a read can still yield a version conflict. No production data, real models, prior benchmark outputs or deployment process is changed by these repairs.

Rerun confirmation reduces accidental loss of the current display but does not provide historical restoration. Recognized-detail summaries still cannot establish group/report completeness; exported comments qualify the existing text without changing the eighteen-column ledger. Cross-batch identity completeness and append remain explicitly unimplemented. Real-sample accuracy and untested hardware/deployments remain outside this verification. Shared Python modules are activated together through an idle coordinated restart.

## Local activation

At the user's explicit restart request on2026-10-12, a consistent integrity-checked SQLite backup precedes stopping all11 identity-verified old processes. A final BEGIN IMMEDIATE gate confirms zero queued/active tasks and an unchanged snapshot before stopping the old tree. The replacement launcher preserves dual_resident mode and binds127.0.0.1:8765; GLM then Paddle finish serial loading/warmup and both report ready. Application1.21.0/schema0005, database/worker/storage health and an empty queue are confirmed. All11 table fingerprints and2,135 owned encrypted files/key fingerprints match the baseline, preserving194 tasks and2 accounts. All13 served static files equal the qualified build; anonymous settings PUT returns401. The [activation record](../../../../output/review-repairs-activation-20261012-v1/activation.json) retains the verification, with backup, process identities, startup transitions and launcher logs alongside it. No task is rerun or account changed for this check; startup warmup is not a new recognition accuracy benchmark.

Later approved [qualified normal summaries and durable refresh reconciliation](2026-10-12-qualified-normal-and-refresh-retry.md) replace the unqualified derived wording and repair retry failures. [Person packages](../feature/2026-10-12-person-material-packages.md) implement the previously deferred append and identity-card material-presence subset; rerun confirmation and the remaining review boundaries stay in effect.
