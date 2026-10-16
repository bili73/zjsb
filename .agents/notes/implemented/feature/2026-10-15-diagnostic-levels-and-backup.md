# Agent Note: Retain searchable diagnostics and verified automatic archives

Status: implemented
Scope: backend/ocr_app, backend/runtime_worker.py, backend/task_worker.py, tests, frontend/src, frontend/tests, scripts/collect_diagnostics.py, RUNTIME.md, SPEC.md, openapi.yaml, frontend/public/help/index.html
Last-verified: 2026-10-15

## Problem

The existing safe JSONL logger has per-instance rotation and seven-day retention, but no severity, automatic archives, aggregate health or server-log UI. Browser errors disappear on refresh. Logging failure is visible only on stderr. The user approved daily backups, administrator-only historical diagnostics, frontend reporting, and explicit failure visibility.

## Decision

[Diagnostic recovery and scan bounds](../bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) extends this design with awaited thread-pool HTTP logging, per-file maintenance isolation and explicit partial-query/ZIP metadata. Damaged sources remain intact while valid records/files remain accessible. Backup checkpoints advance only after atomic persistence. A bounded signature-validated archive metadata index skips unrelated date ranges; content is still verified before emission or deletion.

Retain the allowlisted technical schema and introduce DEBUG/INFO/WARNING/ERROR/CRITICAL, application version, stable record IDs and safe request operation/context. The original INFO default is narrowed to ERROR by the [serious-log and Chinese explanation policy](2026-10-15-error-only-chinese-diagnostics.md); the archive and authorization decisions below remain active. Expected client validation/review conflicts are WARNING; task failures/timeouts are ERROR; unavailable service/storage is CRITICAL. Old records derive their level and identity on read without rewriting originals.

Keep raw logs seven days and verified compressed snapshots thirty days. A dedicated service thread performs daily snapshots and periodic maintenance, independently of OCR watchdog supervision. Before rotation discards a segment or retention removes a raw file, archive and verify that exact snapshot; failure preserves the source. Content-addressed archives deduplicate unchanged snapshots. A cross-process root lock protects append/rotation/snapshot/delete. Raw usage above 512 MiB triggers archival of inactive files; archives have a 1 GiB admission cap and never evict in-retention backups silently. Capacity or backup failure is visible, not reported as success. Same-disk archives provide recovery from log rotation, not disk failure.

History loops hold the lock for one file at a time and periodically yield a 25 ms writer window after 50 ms of background work; OS lock waiters poll every 20 ms. This is deliberate throughput reduction for backups, preventing live startup/request logging from starving behind historical files. A first local activation exposed one model-log write failure while backing up nearly 900 old files; the failure marker and first activation evidence are retained. The follow-up implementation covers the cross-process contention instead of extending the write timeout.

Administrator routes expose safe status, filtered/paged recent and archived events, and a bounded diagnostic ZIP. Revalidate the live admin session after expensive reads. Authenticated frontend error reports are strictly shaped, size/rate bounded, attributed to the authenticated actor and never recursively reported on delivery failure. Ordinary users retain their own current-page cards and cannot query global logs. Logout/account changes clear prior local cards. The header polls admin status only while visible and displays new errors or unavailable recording/backup; server query is user initiated.

The [safe error context extension](../bug-fix/2026-10-15-safe-diagnostic-error-context.md) adds optional allowlisted frontend exception type, browser-event classification and loaded bundle hash, with ErrorEvent numeric fallback and Vue error capture. Legacy report bodies remain accepted. New fields survive queries and both export paths through the same privacy validator; the hash is separate from the server version and is not trusted deployment attestation.

No source images, OCR text, filenames, raw URLs/query strings, credentials or raw exception prose enter logs or bundles. Only fixed route/operation names and opaque identifiers are recorded. This is runtime diagnostics, not the deferred account-operation audit project. Implementation tests use isolated storage and fake model runtimes. Local activation is a separate idle-gated release with a verified database/material/key/static snapshot and dual-model warmup checks; Mac adapter/log rotation must be integrated and tested on its deployment branch separately.

## Decision audit

- [Local diagnostics](2026-09-30-local-diagnostics.md): partially extends severity, retention implementation, archival and UI; keeps privacy and offline-export guarantees. Both notes remain active and linked.
- [Contextual guide](../../implemented/feature/2026-10-15-contextual-operation-guide.md): manual and header overlap only; preserve uncommitted guide work.
- Existing proposed/rejected notes contain no competing diagnostic backup decision. No notes are wholly superseded.

## Alternatives considered

- Keep manual ZIP collection: already works offline and is simple; still requires someone to act before rotation/cleanup, so retain it as a fallback alongside automatic archives.
- Add a central logging stack: rich search and remote alerts; a separate server and agents exceed this application's present needs, so use local files and existing web UI.
- Put log records in the business database: convenient queries; couples diagnostic failures and cleanup to the database being diagnosed. Keep diagnostic storage independent.
- Copy raw stderr/screenshots: useful for arbitrary third-party errors; may disclose credentials or materials. Preserve allowlisted stack/code diagnostics instead.

## Testing

- Reproduce and test severity classification, legacy reading, exact-snapshot archival, rotation, expiry, ZIP corruption/capacity/write failures and restart recovery; never delete an unverified source.
- Prove anonymous/operator/viewer denial for global diagnostics and revoked-admin denial after slow collection, plus report schema/rate/CSRF controls and sensitive-value exclusion.
- Verify frontend query/download/status/UTC+8 display and account switching; reporting failures cannot create recursive cards or disrupt normal tasks.
- Run backend/frontend regression, production build and DDE gates. Use synthetic data for browser evidence, preserve production data and current log backup.

The full backend suite passes 833 tests and frontend passes 214 tests; the production frontend build succeeds. A first backend run failed because optional batch_id=None changed a worker call contract; the corrected optional context is covered by the passing full run. A final diagnostic-only run passes 12 tests, including lookup of browser-generated error IDs. Synthetic browser checks verify admin history/filter/download, failure alerts and viewer isolation. The actual downloaded ZIP passes CRC validation and contains the two filtered ERROR records. The manual describes both online and offline recovery. Evidence, failed runs and synthetic screenshots remain in output/diagnostic-hardening-20261015; they do not represent OCR accuracy testing.

After the activation contention fix, 34 diagnostic/authorization regressions pass plus the final strengthened live-writer test. An isolated 900-file history probe archives while a separate process writes 180 events: zero write failures, all 9,182 total records readable, maximum individual writer wait 0.140 seconds, total probe 63.954 seconds. This measures synthetic log contention, not production OCR throughput or a disk-full guarantee. The 833-test full-suite result precedes this localized contention fix; the affected suites cover the final changes.

## Consequences

Large history scans consume I/O; serialize queries, bound returned pages/downloads and report truncation. Disk exhaustion cannot guarantee the final event; retain in-memory failure state and safe failure markers where possible, and show status separately. Daily snapshots can overlap live writers; shared locks and snapshot verification define the deletion boundary. No claim of remote alert delivery or Mac readiness without separate deployment verification.

The [serious-query restriction](../../implemented/simplification/2026-10-15-serious-diagnostic-query.md) filters product pages and ZIPs before pagination without deleting historical evidence.
