# Agent Note: Preserve actionable error context without private exception prose

Status: implemented
Scope: backend/ocr_app/diagnostics.py, backend/ocr_app/routes.py, frontend/src/diagnostics.ts, frontend/src/main.ts, frontend/src/api.ts, frontend/src/components/DiagnosticsPanel.vue, frontend/tests, tests, SPEC.md, RUNTIME.md, openapi.yaml
Last-verified: 2026-10-15

## Problem

A diagnostic export contains eleven browser errors without code positions or exception types. Before this repair Vue exceptions reached only the console, and database failures were reduced to Exception, hiding the distinction between missing schema and resource contention. Concurrent code updates are a plausible cause of the historical failures; this does not establish an ongoing production defect.

## Decision

Vue errors use the existing diagnostic path and retain console behavior. Browser ErrorEvent records prefer parsed stack positions and fall back to bounded numeric event coordinates. Exact known ResizeObserver and opaque script messages map to fixed categories without retaining message text or suppressing the events. Promise errors remain separately identified.

Add optional frontend exception type, browser-event category and frontend-build fields to authenticated reporting. The build marker is the opaque hash in this application's emitted /assets/index-HASH.js URL, extracted from import.meta.url; unknown/development builds remain null. It identifies the loaded bundle independently of the server version and does not copy any URL or filename. Revalidate all fields through backend allowlists and on export. Preserve old clients, existing CSRF/session/rate/body limits, and non-recursive reporting failure.

Preserve bounded DB-API/SQLAlchemy exception names and SQLite numeric codes. Classify real sqlite3 exceptions into fixed missing-table, missing-column, busy, readonly, constraint, corrupt or other categories using SQLite codes and exact recognized message prefixes; never persist the message, SQL, parameters, table names or database paths. Export applies the same allowlists to saved records. No diagnostic path queries the business database to explain a failure.

## Decision audit

- [Diagnostic archives](../../implemented/feature/2026-10-15-diagnostic-levels-and-backup.md) owns authenticated frontend reporting; extend its context rather than introducing another collector.
- [Local diagnostics](../../implemented/feature/2026-09-30-local-diagnostics.md) owns safe exception serialization; retain the no-message/no-locals boundary.
- [Error-only Chinese descriptions](../../implemented/feature/2026-10-15-error-only-chinese-diagnostics.md) retains capture thresholds and legacy identities.
- [Recovery repairs](../../implemented/bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) retains awaited thread-pool writes, partial availability and bounded metadata indexing.
- Scope queries include unrelated OCR, authentication and export notes; proposed hosted sessions and rejected recognition designs do not decide this extension. No note is superseded or archived.

## Alternatives considered

- Raw browser messages/stacks and SQL exception strings give the most detail, but can contain URLs, credentials or OCR values. Keep bounded types, numeric locations and fixed classifications.
- A new build registry and source-map service would map every bundle to original components, but require publication and retention contracts. Retain the existing emitted bundle hash and minified coordinates; source mapping remains separate work.
- Suppress known browser layout notifications to reduce noise: useful for cleaner dashboards, but would erase evidence before the eleven reported failures are identified. Classify without suppression.

## Testing

- Real Vue-render failures, browser events without Error objects and rejected promises produce bounded cards; detach removes global listeners.
- Frontend report metadata survives backend JSONL, queries and ZIP export; legacy bodies still work and invalid metadata is rejected.
- SQLite missing table/column, contention and constraint cases remain distinguishable without injected SQL, identifiers or secrets escaping local/online/offline exports.
- Relevant/full tests, typecheck, isolated build and DDE pass; production service activation and publication remain separate.

Targeted regressions pass 40 backend diagnostic tests, including real native SQLite failures, SQLAlchemy exception chaining, archive/online/offline revalidation and report schema compatibility. The full backend suite passes 853 tests in 321.567 seconds. All 219 frontend tests and vue-tsc pass. An isolated Vite build succeeds with the existing large-chunk warning; a headless Edge probe loads that actual build against synthetic anonymous HTTP responses and verifies ErrorEvent fallback, Vue handler wiring, the matching b_BgSLQ8no bundle marker and sensitive-value exclusion in downloaded cards. This is not a production-service or real-model test. Evidence, including initial failing probes, remains in tmp/diagnostic-context-20261015/.

DDE verifies 104 active notes plus one archived note; the regenerated index contains 105 notes, 626 relations and zero stale entries. git diff --check passes. The decision records privacy and source-mapping tradeoffs without changing the task/migration policy or claiming a confirmed ongoing incident.

The user-authorized Windows activation on 2026-10-15 publishes this worktree's uncommitted repairs on main at base commit 63638e38ec28c4e9bda05bdfc7d360cb216cb9fb. Version remains 1.26.0 and mode remains dual_resident. The rebuilt frontend matches the validated b_BgSLQ8no bundle. Before stopping the verified launcher tree, an idle-gated consistent SQLite backup and 2,900-file snapshot are completed. After restart all 14 database tables, 268 tasks, two accounts and 2,884 material/key files match the snapshot; all 16 served static files match the build. Public health is ok, protected anonymous requests return 401 and the login page renders. Both owned model process trees are alive with no observed startup failure records; full model readiness is not independently checked because this verification browser has no authenticated session. No account/session is created or changed for the check. See the [activation verification](../../../../output/diagnostic-context-release-20261015-160652/verified.json). Mac deployment, commit and push are not part of this activation.

## Consequences

This enriches future events only. Bundle identifiers are diagnostic context, not trusted deployment attestation. Minified positions do not replace source maps. Exact browser/SQLite message classification can fall back to a generic category on unfamiliar runtimes. Revisit source-map retention if a known bundle plus positions is insufficient to locate recurring faults. No task, migration or retry behavior changes.
