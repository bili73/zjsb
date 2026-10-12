# Agent Note: Browse batches by Shanghai day, week and month

Status: implemented
Scope: backend/ocr_app/routes.py, backend/ocr_app/task_store.py, frontend/src/api.ts, frontend/src/batchCalendar.ts, frontend/src/monitor.ts, frontend/src/components/BatchBoard.vue, frontend/tests, tests/test_business_api.py, backend/ocr_app/api.py, tests/test_runtime_api.py, tests/test_document_contract.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user wants batch organization by day/week/month with a calendar selector. Existing batches are descending but only the latest fifty are initially loaded; filtering that local page alone can incorrectly claim no older batch exists. All session batches share a central monitor so changing the view must not discard in-flight work or freeze its status.

## Decision

Default to day-grouped all-date browsing. Day/week/month controls change grouping, and a corresponding date/week/month picker selects a server-side creation-date range; clearing it restores all dates. Use Shanghai UTC+8 civil dates and Monday-Sunday weeks, including cross-month/year boundaries, regardless of client/host timezone. Within groups retain descending creation order and material-derived names. Undated entries have an explicit synchronization/unknown group rather than a guessed date. The Day.js zh-cn locale is explicitly registered and pinned as a direct dependency; translated widget labels alone do not set Monday weeks. New submissions clear old date filters so the accepted batch is visible. This is a read-only batch browser, not an appointment scheduler.

Add optional date_from/date_to ISO calendar-day query parameters to the existing paginated batch list. Interpret inclusive civil-day bounds as a UTC start-inclusive/end-exclusive interval, validate invalid/reversed/unsupported ranges, filter before count/pagination, and leave the no-filter API compatible. Keep UTC timestamp storage unchanged and add no table/migration.

Keep monitored entries and task polling independent of the selected visible list. Reset only list pagination/IDs when the range changes, use a generation guard against late old-range responses, and abort obsolete view reads. Hidden already-tracked running batches continue polling; clear/logout removes view state. Existing review/export actions still target their explicit batch/selection and are not combined by group.

## Decision audit

- [Element Plus central monitor](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md): partial overlap; keep centralized task ownership, type switching and independent write operations; add filtered list state without deleting tracked entries.
- [Internal presentation](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md): partial overlap; retain UTC+8 display, descending order and material-based names, now add civil-date grouping/filtering.
- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): retain task identities, current states and persistence; range queries are read-only.
- [Independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md): retain production execution; switching the calendar does not cancel recognition.
- Medical summary/export refinement, hosted-auth/Mac proposals and rejected medical thresholds are unrelated. No decision is fully superseded or archived.

## Alternatives considered

- Filter only the loaded fifty batches: least code and no API change, but misses matching history beyond the initial page.
- Fetch all history before filtering: straightforward for today's small volume, but makes reads unbounded and delays calendar browsing as history grows. Keep existing pagination and filter in the store.
- Persist separate day/week/month batch records: can materialize navigation, but duplicates data and couples display grouping to business identities. Derive groups from existing timestamps.
- Clear the central monitor on every selection: makes UI state simple, but loses hidden running jobs and existing snapshots. Reset only visible list pagination.

## Verified invariants

Tests cover Shanghai midnight, leap-month and cross-year Monday week bounds, descending group order, invalid/reversed date API requests, filtering before pagination with correct totals, and unchanged no-filter behavior. Frontend monitor tests prove range changes preserve running tasks, reset paging and ignore stale responses. Build/typecheck, relevant/full backend and frontend tests, isolated real HTTP/browser controls and DDE verify pass. Refresh the idle identity-verified local service with data/accounts/keys preserved after the medical/export changes are jointly qualified.

## Consequences

Week convention is Monday-based and calendar selection matches creation time rather than latest update time. Long-running jobs outside the selected range remain active but are hidden from that view; clearing the date reveals all tracked batches. This does not promise all old jobs fit in memory, qualify Mac or change retention.


## Release verification

The final backend suite passes477 tests in117.560s, the frontend passes70 tests and typecheck/build. The isolated real HTTP/headless Edge probe passes5 checks with zero page errors, real model calls or production writes: automatic two-photo upload, missing-PAN peer isolation, real rotation and retained crop after a synthetic503, one-crop retry with both original results unchanged, and month/week/day picker selection plus clearing. Its initial attempts expose and then fix the missing Day.js locale registration; failed logs/screenshots remain preserved.

Three native medical reports retain7 source-backed liver measurements each (21 total, page14), catalogue counts9/10/11 and abnormal counts7/6/2, with0 model calls and154 unprocessed image regions. XLSX round-trip and rendered QA verify actual liver results,7/6/2 newline anomaly entries, original string identifiers, EF760E nonmedical headers and unchanged medical blue/orange. This is mapping and layout verification, not new full-report or bank OCR accuracy.

After three idle checks, a consistent SQLite backup and confirmed exit of all12 old owned processes, Windows loopback1.17.0 serves the qualified frontend. Both models are ready. The55 existing tasks encrypted fields, one account and key files retain their previous signatures. Evidence: output/bank-auto-20261009-v1/ and output/biochemistry-export-20261009-v1/. No database migration, original sample rewrite, extra semantic model, Mac qualification, commit or push occurs.


## Current refinement

The [batch deletion feature](2026-10-10-delete-recognized-batches.md) invalidates pre-deletion reads, clears only the deleted batch cache and restarts pagination at page two while retaining the current date filter and other jobs. The descending-order test now supplies distinct explicit timestamps, avoiding an unsupported assumption that successive uploads cannot share a wall-clock tick; production timestamp ordering and ID tie-break remain unchanged.

Initial default and new-upload date clearing are partially superseded by the [selected-period fix](../bug-fix/2026-10-09-selected-calendar-period.md): today is initially selected, and uploads reset to today within the chosen period. The all-date default described above records the preceding release. UTC+8, Monday weeks, server pagination and hidden-task monitoring remain active.
