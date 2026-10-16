# Agent Note: Preserve queued work and isolate diagnostic recovery failures

Status: implemented
Scope: backend/ocr_app/task_store.py, backend/ocr_app/retention.py, backend/ocr_app/api.py, backend/ocr_app/routes.py, backend/ocr_app/diagnostics.py, backend/ocr_app/diagnostic_archive.py, backend/ocr_app/diagnostic_service.py, frontend/src, frontend/tests, tests, SPEC.md, RUNTIME.md, openapi.yaml, frontend/public/help/index.html
Last-verified: 2026-10-15

## Problem

Shortening retention can expire an accepted queued rerun before startup resumes the queue. Diagnostic writes wait synchronously on a shared file lock inside async HTTP handlers. A partial JSONL line or corrupt archive aborts unrelated queries and backup work. Repeated history scans decode unchanged archives even outside the requested dates. A resolved guide anchor cannot rebind after disappearing.

## Decision

Exclude QUEUED and active processing states from automatic expiry and use the same set for retention impact counts. Preserve original upload deadlines, explicit cancellation and eventual expiry after processing stops. Do not expand ACTIVE itself because worker recovery and supervision intentionally exclude queued tasks.

Await synchronous diagnostic writes through the existing worker thread pool, including request exception middleware and browser reporting. Keep reporting authorization, CSRF, rate limits and error-only recording. There is no fire-and-forget logging queue.

Isolate scan and maintenance failures to individual owned files. Keep damaged raw files and archives byte-for-byte, continue valid files, and return valid allowlisted records with explicit incomplete/skipped counters. A ZIP exposes the same completeness metadata; capacity truncation remains distinct. Whole-directory access failures still fail with 503. A failed archive never authorizes deletion, and failed maintenance state persistence never counts as a successful backup checkpoint.

Use a per-service LRU index of at most 2048 validated immutable archive metadata entries, bound to filesystem identity, size and timestamps. Skip archives whose verified event ranges cannot intersect the query. Share metadata between maintenance and queries, but revalidate content before deleting an archive or emitting its records. New or changed segments invalidate cached metadata, restart rebuilds it, and no persisted index or business migration is required. Count recent errors while streaming rather than retaining full record objects. Record-ID deduplication still needs a set for the scanned window; matching-window archives remain parsed on every query.

Reset guide resolution when a target is removed, hidden or replaced; retain the existing scope, draft preservation and close/unmount behavior.

## Decision audit

- [Administrator retention](../../implemented/feature/2026-10-15-admin-file-retention.md) partially overlaps: clarify the queued-work deferral boundary; keep confirmed global policies and upload-based clocks.
- [Diagnostic archives](../../implemented/feature/2026-10-15-diagnostic-levels-and-backup.md) partially overlaps: replace whole-scan failure with explicit partial availability while preserving original evidence and authorization.
- [Error-only diagnostics](../../implemented/feature/2026-10-15-error-only-chinese-diagnostics.md) remains the severity/privacy owner; dictionaries and default levels stay intact.
- [Contextual guide](../../implemented/feature/2026-10-15-contextual-operation-guide.md) remains the interaction owner; repair target recovery only.
- Scope queries also match durable tasks, model supervision, shared ownership, export and hosted deployment notes. Their independent decisions remain active. Proposed hosted sessions and rejected extraction/localization alternatives do not decide these repairs. No note is wholly superseded or archived.

## Alternatives considered

- Reset retention from rerun time: gives queued work a grace period, but changes the agreed upload clock and can retain old material indefinitely through reruns. Defer only while accepted work is pending or active.
- A separate asynchronous logging queue can isolate disk latency completely, but adds queue shutdown, overflow and delivery contracts. Await the existing thread pool to retain request-level write outcomes.
- Reject every scan containing damage: ensures callers cannot mistake a partial result for complete history, but makes healthy logs inaccessible during the incident that needs diagnosis. Return explicit partial metadata and preserve damaged sources.
- Store a new persistent log database or retain all parsed records in memory: accelerates arbitrary queries, but adds migration/recovery work or memory growth. Cache bounded verified archive metadata and retain streaming reads for matching records.

## Verification

- An overdue queued rerun survives finite-policy changes and startup cleanup with all artifacts/history intact, remains claimable, and expires only after it stops; impact counts agree.
- A held diagnostic lock does not delay unrelated HTTP health requests, including concurrent error responses; reporting authorization remains enforced.
- Partial raw lines and corrupt ZIPs cannot block healthy records/archives. Responses and UI report skipped data, restart retains evidence, and no unverified source is deleted.
- Archive index hits avoid repeated decompression outside the date window; file replacement, append/rotation, expiration, duplicate records and legacy archives retain correct results.
- Guide target removal/restoration and immediate replacement restore the correct highlight and clean up listeners.
- Synthetic regression logs, full-suite results and performance probes are retained under `tmp/review-repairs-20261015b/`; the initial failing probes and previous review evidence remain intact. Production activation and publication are separate operations.

The final backend suite passes 848 tests in 317.887 seconds. All 216 frontend tests, vue-tsc, and an isolated Vite production build pass. The existing large-chunk build warning remains. DDE verifies 103 active notes plus one archived note and the regenerated index has 104 notes / 620 relations / zero stale entries. `git diff --check` passes. These checks use synthetic business data and fake model runtimes; they do not activate this worktree in the running Windows service or verify real-model accuracy/Mac deployment.

The 40,000-old-record / four-archive synthetic probe measures four archive reads on cold maintenance, then zero historical archive decompressions on both a repeated maintenance pass and a current-day query. The query still returns one recent record. On this machine the current-day query takes 0.0021 s and warm maintenance 0.1163 s; the previous uncached review measured 0.4543 s and 0.6039 s respectively. These are isolated local observations, not a production latency guarantee or OCR accuracy benchmark. The cache is rebuilt on process restart.

These repairs are subsequently activated together with the [safe diagnostic context extension](2026-10-15-safe-diagnostic-error-context.md) in the user's Windows checkout on 2026-10-15. Its activation record verifies preserved database/material/key contents, matching served static files, public health and anonymous authorization; it does not claim an authenticated full model-readiness check or Mac deployment.

## Consequences

Queued files can remain beyond their deadline while processing is unavailable; explicit cancellation restores expiry eligibility. Partial results require callers to honor the additive completeness fields. The archive index is an optimization for application-owned immutable files, not protection against a privileged actor forging filesystem metadata. Metadata-only caching trades some matching-window parsing cost for bounded memory and read-time privacy validation.

Skipping damage keeps healthy evidence available without deleting the damaged source. Skipped counts reflect encountered files/lines, including damaged files whose date cannot be determined; an early size truncation does not claim to inspect later files. All accepted writes still wait for their own result in the thread pool, so a stalled disk can occupy pool workers even though it no longer blocks the event loop. Revisit dedicated logging isolation or a persistent query index only if sustained contention or matching-window scans exceed measured operational needs.

The [serious-query restriction](../../implemented/simplification/2026-10-15-serious-diagnostic-query.md) retains these partial-recovery guarantees while limiting product records to ERROR/CRITICAL.
