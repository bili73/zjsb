# Agent Note: Bound HTTP admission and shorten durable write transactions

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/public/help, frontend/tests, tests, scripts/probe_http_load.py, openapi.yaml, SPEC.md, ARCHITECTURE.md, FRONTEND_FIELDS.md
Last-verified: 2026-10-16

## Problem

The user approves the response to the isolated Windows HTTP load report: 50 readers succeed, while 4/150 uploads and 23/100 exports fail with SQLITE_BUSY at BEGIN IMMEDIATE. Upload and export access-history files are encrypted/fsynced while holding the writer lock. HTTP admission is unbounded by operation, and document subprocesses also write the same database. This is not an OCR capacity measurement.

## Decision

Keep SQLite WAL/FULL and the five-second busy timeout. Centralize short write-transaction handling for TaskStore and Accounts, translating only SQLite busy to an explicit retryable 503; never retry a transaction body. HTTP upload/classification/append share an asynchronous FIFO admission gate before multipart consumption, exports have a separate gate. Initially each lane admits two active requests and at most 64 waiters for up to 15 seconds; each account may occupy at most two upload slots and one export slot, including waiters. Limits are provisional, not measured capacity. No waiting thread or database connection is allocated for the HTTP queue. Revalidate authorization after admission and at mutation/publication boundaries. Queue-full/expiry returns 503; same-account duplication returns 429, with Retry-After. Do not automatically replay writes. Existing drafts/files/selections survive rejected requests.

Prepare upload ciphertext and review history outside write transactions; commit references and business state together after rechecking authorization, version and required-field policy. Duplicate staged files and rejected preparations are removed; crash leftovers are reclaimed only by existing exclusive-startup orphan cleanup. Export reads a consistent snapshot and generates its workbook outside a write transaction, stages history, then atomically rechecks selected task/batch/policy revisions and records history plus successful export. Failed preparation never records successful export. Retain rollback, fsync, account isolation and same-version CAS. Subprocess writers use the same busy classification; SQLite remains the cross-process lock authority. This is not a process-local lock presented as global coordination.

Expose only safe numeric queue/DB wait and hold timings in response headers for isolated measurement. Normal saturation is a controlled response and does not recursively insert failure audit records into a busy database or create ERROR diagnostics. Genuine unexpected failures retain diagnostics. No schema migration, PostgreSQL/Redis deployment, inference policy change, production restart, or Git publication is part of implementation validation.

Queue timing is emitted after admission; rejected admission omits that header rather than reporting an unknown wait as zero. The upload and export lanes do not serialize reads or independent model execution. Review keeps short CAS writes without a new admission lane.

## Decision audit

- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): partial overlap; retain durable 202, encrypted files, recovery and version checks, shorten lock scope.
- [Independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md): partial overlap; retain process isolation and independent model FIFO, cover real worker DB writers separately.
- [Authorization boundaries](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md): partial overlap; queue waiting cannot retain revoked authorization.
- [Action audit](../../implemented/simplification/2026-10-16-account-action-audit.md): partial overlap; export success is committed with its history; overload rejections are not completed business actions.
- [HTTP concurrency evidence](../../implemented/testing/2026-10-16-http-concurrency-capacity.md): complementary; keep original failed measurements and separate controlled rejections from successes.
- Scope/topic search finds no competing proposed/rejected backpressure decision. Existing unrelated edits stay intact.

## Alternatives considered

- Increase busy_timeout: inexpensive burst tolerance, but extends blocked threads and does not shorten lock ownership. Preserve it while fixing the lock scope.
- Add workers/connections: helps CPU-independent work, but adds competitors for SQLite's single writer. Do not scale these blindly.
- PostgreSQL or a dedicated writer RPC: stronger multi-process/multi-host coordination, but adds migration or protocol complexity before measuring short transactions. Reconsider if sustained load remains unacceptable.
- Keep file I/O inside transactions: straightforward rollback ownership, but blocks unrelated users during fsync. Stage encrypted artifacts, commit references atomically, retain cleanup/recovery tests.

## Verification scope

Test FIFO/cancellation/timeout/overflow/account isolation, pre-body admission, authorization revoked while waiting/building, CAS conflict and policy changes, staged-file cleanup on failure, separate-process writer contention, and preservation of drafts on 429/503. Rerun the same HTTP load protocol, preserving raw results and reporting successful/rejected/failed counts separately, plus lock timing and integrity. Include isolated mixed worker-publication/write regression; real inference and Mac performance remain separately unqualified.

## Verification evidence

The final isolated full protocol, http-load-20261016-160052-837652, records 14,315 requests with no unexpected failures, SQLite busy/HTTP 500, or controlled rejections. Fifty-user upload/save/export bursts succeed 150/150, 150/150 and 100/100; P95 is 6758/3200/9127 ms versus baseline 6052/4439/12175 ms. Upload tail latency increases in this run while its four failures disappear; do not claim every operation becomes faster. Exactly one of fifty same-version reviews succeeds and forty-nine conflict. All 211 acknowledged uploads, fifty corrected values/revisions and 1705 encrypted artifact references pass; no missing, orphaned or corrupt files. Frozen backend hashes match current code. Raw runs and machine-readable timing data are linked from [the comparison report](../../../../output/backpressure-20261016/REPORT.md).

Earlier two full reruns eliminate the 27 baseline SQLITE_BUSY errors but each has one transport error; both remain failed measurements. A focused run also has a background health connection error: its original outcome omitted background requests, so final-verification.json corrects acceptance without overwriting historical evidence. The probe now checks every recorded request. The next diagnostic run reproduces two failures, matching each failed request's local TCP port to a server keepalive close 25/38 ms after submission, with no ASGI arrival. Client and server both expired idle connections at five seconds. The final run changes only the probe client's idle expiry to four seconds, retains the server's five seconds and the 30-second request timeout, and disables optional connection tracing. This is a disclosed harness condition change, not an application timeout increase or automatic write retry; it does not certify browser/proxy connection behavior. Use --client-keepalive 5 --trace-connections to investigate the original race.

Frontend 243 tests, typecheck and isolated build pass. New tests execute actual Vue save/export/upload handlers to retain drafts, selected files and selections on 429/503 without replay. The final 293-case backend regression passes in 253.236 seconds, including the thirteen new contention/staging cases, external-process SQLite busy translated to HTTP 503, independent worker publication, retention, auth revocation, account isolation and export/version invariants (tmp/backpressure-backend-final.log). An injected post-commit response-read failure preserves the committed review and its encrypted history. Earlier fixture/import failures are retained separately. No production activation is implied by build or test success.

## Consequences

Queues absorb bursts but cannot increase sustained SQLite write capacity. Large multipart inputs remain memory-resident, now bounded by admitted requests, not proven safe at maximum sizes. Staged files can be left by process termination until exclusive startup cleanup. Finite queue waits can still reject legitimate bursts; frontend retains input and does not promise the request was accepted. The deployment's single HTTP process is assumed; multiple API processes would need a shared admission boundary.

The original HTTP protocol covers small uploads, review and two-row exports. Preview/reveal access-history still writes files inside its transaction, and worker publication still encrypts result JSON under the write lock. The separate-process regression covers worker progress/attempt/publication alongside HTTP-side store operations, not GPU inference latency or maximum medical/table payloads. These unmeasured paths remain explicit follow-up boundaries.
