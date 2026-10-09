# Agent Note: Name workbench Excel downloads by material type and export time

Status: implemented
Scope: frontend/src/review.ts, frontend/src/components/ExportControls.vue, frontend/src/components/TaskResultDrawer.vue, frontend/tests/review.test.ts, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-09

## Problem

The user requests current recognition type plus time for Excel names. Batch downloads currently use truncated IDs and only an optional date, while single-result downloads use source filenames with no time. Names do not consistently identify the exported material.

## Decision

All three workbench download actions use Chinese material labels and a Shanghai UTC+8 export-start timestamp: 体检报告_20261009_151530.xlsx. Combine distinct types with + for a mixed selection; unknown or missing types use 识别结果 without copying untrusted filenames. Capture the filename from the same selected tasks before awaiting the export, so changing the visible selection during the request cannot rename its content. Keep workbook sheets, saved-value eligibility and backend export bytes/API unchanged. This is the browser download naming policy; direct API Content-Disposition remains its existing fallback.

## Decision audit

The [business workbook](../../implemented/feature/2026-10-09-business-xlsx-layout.md) partially overlaps for export actions and remains active for content, layout and snapshot checks. The [presence gate](../../implemented/simplification/2026-10-08-required-fields-only-export.md) is unchanged. The [selected calendar period](../bug-fix/2026-10-09-selected-calendar-period.md) is an independent concurrently requested frontend fix. Medical, bank recognition, authorization and runtime deployment policies remain active. No existing decision is reversed or fully absorbed.

## Alternatives considered

- Keep source filenames or batch IDs: useful for tracing a single upload, but they do not meet the requested recognition-type naming and vary between actions.
- Change backend response headers and the BusinessApi blob contract: would centralize naming for direct clients, but requires a backend refresh and changes unrelated consumers. The workbench already owns the actual download name, so change its shared helper and callers.
- Use browser local time: easy to format, but conflicts with the approved UTC+8 behavior when another client timezone is used.

## Consequences

The workbench consistently identifies exported types and UTC+8 export-start time. Same-type exports in the same second may share a suggested name; the browser manages duplicates. Direct API clients retain the legacy Content-Disposition fallback. Worksheet content and saved-field gates stay unchanged.

## Verification

The relevant backend suite passes101 tests in23.430s; the frontend passes71 tests and typecheck/build. The final synchronized OpenAPI documentation passes10 contract tests. CUA verifies default today, October8 selection, explicit all dates, Monday week and month boundaries, and a new synthetic upload returning from October8 to today's day range. Batch, selected and single downloads produce actual 银行卡_20261009_HHmmss.xlsx files; all three reopen with unchanged saved card fields. Mixed-type and Shanghai-midnight names are covered by unit tests.

Three serial native-PDF replays retain7 liver measurements per report but leave the liver ledger cell empty, with project counts9/10/11 and abnormal counts7/6/2 unchanged. They make0 model calls and leave154 image regions pending; this is mapping verification, not complete OCR accuracy. Initial browser automation/download timeout and the unavailable-engine fixture are preserved; the ready-engine fixture completes, stops cleanly and makes0 real model calls or production task writes.

After three idle checks and a consistent SQLite backup, all12 identity-verified old owned processes exit. Windows loopback1.17.1 serves all4 qualified frontend files with matching HTTP hashes; both models are ready. The61 original tasks encrypted fields, one account and key files retain their signatures. The actual production page shows only October9's6 batches by default and only October8's14 after selection. Evidence is in output/calendar-period-20261009-v1/. No migration, original sample rewrite, Mac qualification, commit or push occurs.
