# Agent Note: Default calendar browsing to the selected period

Status: implemented
Scope: frontend/src/components/BatchBoard.vue, frontend/src/App.vue, frontend/src/batchCalendar.ts, frontend/tests, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user sees October8 and October9 together while Day is selected. Read-only production inspection confirms correct UTC+8 timestamps and distinct date groups; the visible Day control only changes grouping while the default null date anchor still lists all dates. Thus the defect is the default viewing scope, not corrupt stored dates. Earlier browser coverage verified group headings and explicit picker filtering but did not assert the initial scope.

## Decision

Initialize the calendar with today's Shanghai civil date and immediately filter the server-side batch list to that day. Day/week/month select the period containing the chosen anchor, so each view shows only that selected period. Clearing the date or pressing All dates explicitly opts into all-history browsing with separate group headings. New uploads, including a recovered bank crop, reset the anchor to today in the current period so the accepted batch is visible. Keep hidden running tasks and existing result snapshots monitored; no source, task, backend API, timestamp or queue mutation is required.

Expose a narrow upload-reset counter from App to BatchBoard instead of clearing the monitor's date range on each upload. The board owns the selected period and can select its correct today's interval. Reusing an unchanged today anchor must still reapply the range; clearing a server range and relying on an unchanged computed anchor can otherwise show all dates under a day label.

## Decision audit

This partially supersedes the [calendar browser](../../implemented/feature/2026-10-09-batch-calendar-browser.md) only for its all-dates initial default and upload-reset semantics. The UTC+8, Monday week, filtered pagination, late-response guards and tracked task ownership remain active. The [frontend monitor](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) remains active. Bank/medical recognition, exports, authentication and Mac proposals are unrelated; no note is fully absorbed or archived.

## Alternatives considered

- Retain all dates with stronger headings: keeps history immediately visible, but Day still displays both days, which is the user's explicit complaint.
- Make every date a collapsible folder: provides stronger visual separation, but still shows multiple days by default and adds another navigation layer instead of using the existing picker.
- Filter only browser-loaded batches: avoids a request, but older matching history can be absent and totals inaccurate. Keep the existing backend range filter.
- Clear all monitored entries when selecting a date: makes the visible scope simple, but abandons hidden running tasks and saved results. Change only view scope.

## Consequences

Selecting a period narrows the initial view; older days require the picker or explicit All dates. Hidden running jobs remain tracked. There is no automatic midnight refresh or retention change. The calendar code itself changes only frontend assets; the jointly authorized liver correction requires the backend service refresh recorded below.

## Verification

The relevant backend suite passes101 tests in23.430s; the frontend passes71 tests and typecheck/build. The final synchronized OpenAPI documentation passes10 contract tests. CUA verifies default today, October8 selection, explicit all dates, Monday week and month boundaries, and a new synthetic upload returning from October8 to today's day range. Batch, selected and single downloads produce actual 银行卡_20261009_HHmmss.xlsx files; all three reopen with unchanged saved card fields. Mixed-type and Shanghai-midnight names are covered by unit tests.

Three serial native-PDF replays retain7 liver measurements per report but leave the liver ledger cell empty, with project counts9/10/11 and abnormal counts7/6/2 unchanged. They make0 model calls and leave154 image regions pending; this is mapping verification, not complete OCR accuracy. Initial browser automation/download timeout and the unavailable-engine fixture are preserved; the ready-engine fixture completes, stops cleanly and makes0 real model calls or production task writes.

After three idle checks and a consistent SQLite backup, all12 identity-verified old owned processes exit. Windows loopback1.17.1 serves all4 qualified frontend files with matching HTTP hashes; both models are ready. The61 original tasks encrypted fields, one account and key files retain their signatures. The actual production page shows only October9's6 batches by default and only October8's14 after selection. Evidence is in output/calendar-period-20261009-v1/. No migration, original sample rewrite, Mac qualification, commit or push occurs.
